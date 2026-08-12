"""NDJSON bridge runtime — same actions the Qt UI used to drive."""

from __future__ import annotations

import threading
import traceback
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from acars_bridge import __version__
from acars_bridge.models.settings import SettingsStore
from acars_bridge.network import all_profiles
from acars_bridge.printing.discovery import list_printer_choices
from acars_bridge.services.actions import ActionError, PrinterActions
from acars_bridge.services.debug_log import DebugLog
from acars_bridge.services.session import AppSession
from acars_bridge.services.updater import (
    UpdateError,
    can_auto_install,
    check_for_update,
    current_executable,
    download_release,
    schedule_windows_replace_and_restart,
    shell_wait_pid,
)
from acars_bridge.tap.service import TapService, TapStatus


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _err(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


def _debug_log_path(fallback_root: Path) -> Path:
    """Prefer the support log next to the desktop EXE when the shell provides it."""
    import os

    raw = (os.environ.get("ACARS_BRIDGE_EXE_LOG") or "").strip()
    if raw:
        path = Path(raw)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            return path
        except OSError:
            pass
    return fallback_root / "debug.log"


@dataclass
class FakeTapService:
    """In-process tap stand-in for unit tests (no Admin / WinDivert)."""

    session: AppSession
    on_update: Callable[[TapStatus], None] | None = None
    on_new_messages: Callable[[int], None] | None = None
    on_debug: Callable[[str], None] | None = None
    status: TapStatus = field(default_factory=TapStatus)
    checks: int = 0

    def start(self) -> None:
        if self.status.running:
            return
        profile = self.session.settings.network_profile()
        self.status.running = True
        self.status.last_error = None
        self.status.last_check = datetime.now(UTC)
        self.status.network_id = profile.id.value
        self.status.network_label = profile.label
        self.status.last_mode = "tap"
        if self.on_update:
            self.on_update(self.status)

    def stop(self) -> None:
        self.status.running = False
        self.status.last_check = None
        if self.on_update:
            self.on_update(self.status)

    def check_now(self) -> None:
        self.checks += 1
        self.status.last_check = datetime.now(UTC)
        if self.on_update:
            self.on_update(self.status)


TapFactory = Callable[..., Any]


class BridgeRuntime:
    """Owns AppSession + tap + actions; handles bridge commands and events."""

    def __init__(
        self,
        session: AppSession,
        *,
        tap_factory: TapFactory | None = None,
        clear_messages_on_boot: bool = False,
        debug: DebugLog | None = None,
        background_tick: bool = True,
    ) -> None:
        self.session = session
        self._clear_on_boot = clear_messages_on_boot
        self._booted = False
        self._closed = False
        self._events: deque[dict[str, Any]] = deque(maxlen=200)
        self._events_lock = threading.Lock()
        self._user_check_pending = False
        self._tick_lock = threading.Lock()
        self._simbrief_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="simbrief-poll"
        )
        self._simbrief_poll_pending = False
        self._power_was_blocking: bool | None = None
        self._power_was_sterile: bool | None = None
        self._power_was_unpowered: bool | None = None
        self._power_was_powered: bool | None = None
        self._last_simconnect_detail: str | None = None
        self.debug = debug or DebugLog(
            _debug_log_path(session.paths.root),
            get_logon=session.settings.hoppie_logon,
            get_extra_logons=lambda: [
                x
                for x in [session.wire_session.active_logon()]
                if x
            ],
        )
        self.actions = PrinterActions(session)
        factory = tap_factory or TapService
        self.tap = factory(
            session,
            on_update=self._on_tap_update,
            on_new_messages=self._on_new_messages,
            on_debug=lambda msg: self.debug.info("tap_dbg", message=msg),
        )
        session.ensure_auto_wx()
        session.ensure_simbrief_watcher()
        from acars_bridge.companion.server import CompanionServer
        from acars_bridge.services.companion_station import CompanionStationPoller

        self.companion_poller = CompanionStationPoller(
            session,
            on_ingest=lambda n: self._on_new_messages(n),
            on_callsign_conflict=lambda msg: self.emit_event(
                "toast", {"message": msg, "error": True}
            ),
        )
        self.companion_server = CompanionServer(self, poller=self.companion_poller)
        try:
            session.simconnect.start()
        except Exception:
            pass
        self._sync_companion()
        self._tick_stop = threading.Event()
        self._tick_thread: threading.Thread | None = None
        if background_tick:
            self._tick_thread = threading.Thread(
                target=self._background_tick_loop,
                name="bridge-tick",
                daemon=True,
            )
            self._tick_thread.start()

    # --- events -------------------------------------------------------------

    def emit_event(self, event: str, data: Any) -> None:
        with self._events_lock:
            self._events.append({"ok": True, "event": event, "data": data})

    def drain_events(self) -> list[dict[str, Any]]:
        with self._events_lock:
            items = list(self._events)
            self._events.clear()
        return items

    def _on_tap_update(self, status: TapStatus) -> None:
        payload = self.build_status()
        self.emit_event("status", payload)
        stats = status.last_stats or {}
        if status.last_error and not status.running:
            self.emit_event("toast", {"message": status.last_error, "error": True})
        printed = int(stats.get("printed", 0) or 0)
        stored = int(stats.get("stored", 0) or 0)
        if printed or stored:
            parts = []
            if printed:
                parts.append(f"{printed} printed")
            if stored:
                parts.append(f"{stored} stored")
            self.emit_event("toast", {"message": ", ".join(parts), "error": False})
        if self._user_check_pending:
            self._user_check_pending = False

    def _on_new_messages(self, count: int) -> None:
        if count <= 0:
            return
        self.emit_event("new_messages", {"count": count})
        self.emit_event(
            "notify",
            {"title": "ACARS Print Bridge", "body": f"{count} new message(s)"},
        )

    # --- settings serialization ---------------------------------------------

    def serialize_settings(self) -> dict[str, Any]:
        s = self.session.settings
        data = {
            "callsign": s.callsign() or "",
            "aircraft_registration": s.aircraft_registration() or "",
            "acars_network": s.acars_network().value,
            "networks": [
                {"id": p.id.value, "label": p.label} for p in all_profiles()
            ],
            "printer_destination": s.printer_destination(),
            "paper_width": s.paper_width(),
            "cut_enabled": s.cut_enabled(),
            "print_render_mode": s.print_render_mode(),
            "print_glyph_px": s.print_glyph_px(),
            "print_line_gap_px": s.print_line_gap_px(),
            "print_font": s.print_font(),
            "print_char_width": s.print_char_width(),
            "print_char_height": s.print_char_height(),
            "print_bold": s.print_bold(),
            "print_columns": s.print_columns(),
            "print_line_spacing_dots": s.print_line_spacing_dots(),
            "print_lead_in": s.print_lead_in(),
            "print_tear_feed": s.print_tear_feed(),
            "auto_print": s.auto_print(),
            "auto_connect": s.auto_connect(),
            "check_updates": s.check_updates(),
            "printable_types": sorted(s.printable_types()),
            "printable_type_choices": list(SettingsStore.PRINTABLE_TYPE_CHOICES),
            "simbrief_ofp_tickets": sorted(s.simbrief_ofp_tickets()),
            "ofp_ticket_choices": list(SettingsStore.OFP_TICKET_CHOICES),
            "wx_auto_enabled": s.wx_auto_enabled(),
            "wx_auto_nm": s.wx_auto_nm(),
            "wx_auto_kinds": sorted(s.wx_auto_kinds()),
            "wx_auto_kind_choices": list(SettingsStore.WX_AUTO_KIND_CHOICES),
            "hotkeys_enabled": s.hotkeys_enabled(),
            "hotkey_bindings": s.hotkey_bindings(),
            "hotkey_actions": list(SettingsStore.HOTKEY_ACTIONS),
            "sterile_agl_ft": s.sterile_agl_ft(),
            "sterile_agl_choices": list(s.sterile_agl_choices()),
            "print_when_powered": s.print_when_powered(),
            "simbrief_user": s.simbrief_user() or "",
            "simbrief_enabled": s.simbrief_enabled(),
            "simbrief_post_landing_grace_seconds": s.simbrief_post_landing_grace_seconds(),
            "active_print_profile": s.active_print_profile(),
            "has_hoppie_logon": bool(s.hoppie_logon()),
            "companion_enabled": s.companion_enabled(),
            "companion_station_enabled": s.companion_station_enabled(),
            "companion_port": s.companion_port(),
            "companion_token": "",
            "companion_url": "",
        }
        if s.companion_enabled():
            try:
                from acars_bridge.companion.lan import primary_lan_ip

                ip = primary_lan_ip()
                data["companion_url"] = f"http://{ip}:{s.companion_port()}/"
            except Exception:
                pass
        return data

    def apply_settings(self, args: dict[str, Any]) -> dict[str, Any]:
        s = self.session.settings
        if "callsign" in args:
            s.set_callsign(str(args.get("callsign") or ""))
        if "aircraft_registration" in args:
            s.set_aircraft_registration(str(args.get("aircraft_registration") or ""))
        if "hoppie_logon" in args:
            # UI sends a new code only when the password field was edited.
            # Empty / whitespace means leave the stored logon unchanged.
            cleaned = str(args.get("hoppie_logon") or "").strip()
            if cleaned:
                s.set_hoppie_logon(cleaned)
        if "acars_network" in args:
            s.set_acars_network(str(args["acars_network"]))
        if "auto_print" in args:
            s.set_auto_print(bool(args["auto_print"]))
        if "auto_connect" in args:
            s.set_auto_connect(bool(args["auto_connect"]))
        if "check_updates" in args:
            s.set_check_updates(bool(args["check_updates"]))
        if "printable_types" in args:
            s.set_printable_types(args["printable_types"] or [])
        if "simbrief_ofp_tickets" in args:
            s.set_simbrief_ofp_tickets(args["simbrief_ofp_tickets"] or [])
        if "wx_auto_enabled" in args:
            s.set_wx_auto_enabled(bool(args["wx_auto_enabled"]))
        if "wx_auto_nm" in args:
            s.set_wx_auto_nm(args["wx_auto_nm"])
        if "wx_auto_kinds" in args:
            s.set_wx_auto_kinds(args["wx_auto_kinds"] or [])
        if "hotkeys_enabled" in args:
            s.set_hotkeys_enabled(bool(args["hotkeys_enabled"]))
        if "hotkey_bindings" in args and isinstance(args["hotkey_bindings"], dict):
            s.set_hotkey_bindings({str(k): str(v) for k, v in args["hotkey_bindings"].items()})
        if "sterile_agl_ft" in args:
            s.set_sterile_agl_ft(args["sterile_agl_ft"])
        if "print_when_powered" in args:
            s.set_print_when_powered(bool(args["print_when_powered"]))
        if "simbrief_user" in args:
            s.set_simbrief_user(str(args.get("simbrief_user") or ""))
        if "simbrief_enabled" in args:
            s.set_simbrief_enabled(bool(args["simbrief_enabled"]))
        if "simbrief_post_landing_grace_seconds" in args:
            s.set_simbrief_post_landing_grace_seconds(
                args["simbrief_post_landing_grace_seconds"]
            )
        if "companion_enabled" in args:
            s.set_companion_enabled(bool(args["companion_enabled"]))
        want_station = bool(args.get("companion_station_enabled")) if (
            "companion_station_enabled" in args
        ) else None
        if want_station is not None:
            s.set_companion_station_enabled(want_station)
        if "companion_port" in args:
            s.set_companion_port(args["companion_port"])
        self.session.apply_sterile_settings()
        watcher = self.session.ensure_simbrief_watcher()
        watcher.config.post_landing_grace_seconds = float(
            s.simbrief_post_landing_grace_seconds()
        )
        self.session.rebuild_printer(use_fake_printer=s.printer_destination() == "fake")
        station_blocked = self._sync_companion()
        data = self.serialize_settings()
        if want_station and station_blocked:
            data["station_blocked"] = station_blocked
        return data

    def apply_format(self, args: dict[str, Any]) -> dict[str, Any]:
        s = self.session.settings
        if "printer_destination" in args:
            s.set_printer_destination(str(args.get("printer_destination") or ""))
        if "paper_width" in args:
            s.set_paper_width(str(args["paper_width"]))
        if "cut_enabled" in args:
            s.set_cut_enabled(bool(args["cut_enabled"]))
        if "print_render_mode" in args:
            s.set_print_render_mode(str(args["print_render_mode"]))
        if "print_glyph_px" in args:
            s.set_print_glyph_px(args["print_glyph_px"])
        if "print_line_gap_px" in args:
            s.set_print_line_gap_px(args["print_line_gap_px"])
        if "print_font" in args:
            s.set_print_font(str(args["print_font"]))
        if "print_char_width" in args:
            s.set_print_char_width(args["print_char_width"])
        if "print_char_height" in args:
            s.set_print_char_height(args["print_char_height"])
        if "print_bold" in args:
            s.set_print_bold(bool(args["print_bold"]))
        if "print_columns" in args:
            s.set_print_columns(args["print_columns"])
        if "print_line_spacing_dots" in args:
            s.set_print_line_spacing_dots(args["print_line_spacing_dots"])
        if "print_lead_in" in args:
            s.set_print_lead_in(args["print_lead_in"])
        if "print_tear_feed" in args:
            s.set_print_tear_feed(args["print_tear_feed"])
        self.session.rebuild_printer(use_fake_printer=s.printer_destination() == "fake")
        return self.serialize_settings()

    # --- status / messages --------------------------------------------------

    def _clock_chip(self) -> dict[str, str]:
        from acars_bridge.simbrief.watcher import default_clock

        snap = self.session.simconnect.snapshot()
        connected = bool(snap and getattr(snap, "connected", False))
        label = "SIM" if connected else "UTC"
        now = default_clock(snap)
        return {"id": "clock", "text": f"{label} {now.strftime('%H:%MZ')}"}

    def _flt_chip(self) -> dict[str, str]:
        cs = self.session.settings.callsign() or ""
        text = f"FLT {cs}" if cs else "FLT ALL"
        tip = f"Filter: {cs}" if cs else "Printing all flights seen"
        return {"id": "flt", "text": text, "tip": tip}

    def _link_chip(self) -> dict[str, Any]:
        from acars_bridge.hoppie.parser import hoppie_error_label

        st = self.tap.status
        note = (getattr(st, "last_note", None) or "").strip()
        err = (st.last_error or "").strip()
        hoppie_err = (getattr(st, "last_hoppie_error", None) or "").strip()
        wire = self.session.wire_session.status_dict()
        from_cs = str(wire.get("from") or "").strip()
        tip = hoppie_err or err or note
        if not st.running:
            return {"id": "link", "text": "LINK off", "state": "off", "tip": tip}
        if hoppie_err:
            return {
                "id": "link",
                "text": hoppie_error_label(hoppie_err),
                "state": "warn",
                "tip": hoppie_err,
            }
        if err and "trust setup" not in err.lower() and "sim traffic only" not in err.lower():
            hhmm = st.last_check.strftime("%H:%M") if st.last_check else "--:--"
            return {
                "id": "link",
                "text": f"LINK issue · {hhmm}Z",
                "state": "warn",
                "tip": err,
            }
        if from_cs:
            return {
                "id": "link",
                "text": f"Hoppie ok · {from_cs}",
                "state": "ok",
                "tip": tip or f"Aircraft session {from_cs}.",
            }
        if st.exchanges:
            return {
                "id": "link",
                "text": f"Hoppie ok · {st.exchanges} seen",
                "state": "ok",
                "tip": tip or "Aircraft ACARS exchanges seen.",
            }
        return {
            "id": "link",
            "text": "Waiting for aircraft",
            "state": "busy",
            "tip": tip or "Connect is on. Use ACARS in the sim.",
        }

    def _power_chip(self) -> dict[str, str]:
        from acars_bridge.simconnect.monitor import SimSnapshot, aircraft_is_powered

        snap = self.session.simconnect.snapshot()
        acars_n, sb_n = self.session.sterile.queue_sizes()
        queued = acars_n + sb_n if self.session.sterile.require_powered else 0
        connected = isinstance(snap, SimSnapshot) and snap.connected
        if not connected:
            return {
                "id": "pwr",
                "text": "PWR —",
                "tip": "Aircraft power unknown — SimConnect not connected",
            }
        powered = aircraft_is_powered(snap)
        if self.session.sterile.is_settling:
            label = "PWR settle" if not queued else f"PWR settle · q{queued}"
            return {
                "id": "pwr",
                "text": label,
                "tip": (
                    "Power on — waiting ~10 s before printing queued strips "
                    f"(ACARS {acars_n}, SimBrief {sb_n})."
                ),
            }
        if powered is True:
            label = "PWR on" if not queued else f"PWR on · q{queued}"
            tip = "Aircraft powered"
            if self.session.sterile.require_powered:
                tip += " — Only-when-powered: prints allowed."
            return {"id": "pwr", "text": label, "tip": tip}
        if powered is False:
            label = "PWR off" if not queued else f"PWR off · q{queued}"
            tip = "Aircraft unpowered"
            if self.session.sterile.require_powered:
                tip += (
                    f" — Only-when-powered: prints queued "
                    f"(ACARS {acars_n}, SimBrief {sb_n})."
                )
            return {"id": "pwr", "text": label, "tip": tip}
        return {
            "id": "pwr",
            "text": "PWR …",
            "tip": "Waiting for first electrical sample from SimConnect.",
        }

    def _sterile_chip(self) -> dict[str, str]:
        from acars_bridge.simconnect.monitor import SimSnapshot

        snap = self.session.simconnect.snapshot()
        sterile = self.session.sterile.is_sterile
        connected = isinstance(snap, SimSnapshot) and snap.connected
        acars_n, sb_n = self.session.sterile.queue_sizes()
        queued = acars_n + sb_n if sterile else 0
        if not connected:
            return {
                "id": "sterile",
                "text": "STERILE —",
                "tip": "MSFS not connected via SimConnect",
            }
        if sterile:
            label = "STERILE on" if not queued else f"STERILE q{queued}"
            return {
                "id": "sterile",
                "text": label,
                "tip": (
                    f"Printing muted below {int(self.session.sterile.thresholds.agl_ft)} "
                    f"ft AGL or ≥40 kt on ground."
                ),
            }
        return {"id": "sterile", "text": "STERILE off", "tip": "Sterile gate clear"}

    def _ofp_chip(self) -> dict[str, str]:
        watcher = self.session.ensure_simbrief_watcher()
        return {
            "id": "ofp",
            "text": f"OFP {watcher.chip_text()}",
            "tip": watcher.status_detail(),
        }

    def build_status(self) -> dict[str, Any]:
        st = self.tap.status
        link = self._link_chip()
        snap = self.session.simconnect.snapshot()
        return {
            "running": bool(st.running),
            "exchanges": st.exchanges,
            "last_error": st.last_error,
            "network_id": st.network_id,
            "network_label": st.network_label
            or self.session.settings.network_profile().label,
            "link": link,
            "chips": {
                "flt": self._flt_chip()["text"],
                "link": link["text"],
                "pwr": self._power_chip()["text"],
                "sterile": self._sterile_chip()["text"],
                "ofp": self._ofp_chip()["text"],
                "clock": self._clock_chip()["text"],
            },
            "chip_tips": {
                "flt": self._flt_chip().get("tip", ""),
                "link": link.get("tip", ""),
                "pwr": self._power_chip().get("tip", ""),
                "sterile": self._sterile_chip().get("tip", ""),
                "ofp": self._ofp_chip().get("tip", ""),
            },
            "auto_print": self.session.settings.auto_print(),
            "sim_connected": bool(snap and getattr(snap, "connected", False)),
        }

    def _serialize_message(self, msg: Any, *, include_body: bool = False) -> dict[str, Any]:
        preview = (msg.normalized_body or "").replace("\n", " ")
        if len(preview) > 40:
            preview = preview[:40] + "…"
        print_status = self.session.messages.latest_print_status(msg.id)
        if print_status == "printed":
            mark = "PRN"
        elif print_status == "failed":
            mark = "FAIL"
        else:
            mark = "—"
        station = msg.sender if msg.direction == "in" else (msg.to_station or msg.recipient)
        row = {
            "id": msg.id,
            "received_at": msg.received_at,
            "direction": msg.direction,
            "station": station or "",
            "message_type": msg.message_type,
            "print_status": print_status,
            "print_mark": mark,
            "preview": preview,
            "callsign": msg.callsign,
        }
        if include_body:
            row["normalized_body"] = msg.normalized_body
            row["raw_payload"] = msg.raw_payload
            row["sender"] = msg.sender
            row["recipient"] = msg.recipient
            row["to_station"] = msg.to_station
        return row

    def list_messages(self, limit: int = 80) -> list[dict[str, Any]]:
        return [self._serialize_message(m) for m in self.session.messages.list_recent(limit)]

    # --- command handlers ---------------------------------------------------

    def handle(self, command: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        try:
            handler = getattr(self, f"cmd_{command}", None)
            if handler is None:
                return _err(f"Unknown command: {command}")
            return handler(args)
        except ActionError as exc:
            return _err(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.debug.error("bridge", message=str(exc))
            return _err(f"{exc}\n\n{traceback.format_exc(limit=4)}")

    def cmd_boot(self, _args: dict[str, Any]) -> dict[str, Any]:
        # Keep message history for phone companion / past strips.
        if self._clear_on_boot and not self._booted:
            self.session.messages.clear_all()
        self._booted = True
        self.debug.info("boot", version=__version__)
        self._sync_companion()
        data = {
            "meta": {
                "version": __version__,
                "product": "ACARS Print Bridge",
                "data_dir": str(self.session.paths.root),
            },
            "settings": self.serialize_settings(),
            "status": self.build_status(),
            "messages": self.list_messages(limit=80),
            "printers": self._printers(),
            "profiles": self._profiles(),
            "companion": self._companion_info(),
        }
        self.emit_event("status", data["status"])
        return _ok(data)

    def cmd_get_settings(self, _args: dict[str, Any]) -> dict[str, Any]:
        return _ok(self.serialize_settings())

    def cmd_save_settings(self, args: dict[str, Any]) -> dict[str, Any]:
        was_running = self.tap.status.running
        prev_net = self.session.settings.acars_network()
        settings = self.apply_settings(args)
        if self.session.settings.acars_network() != prev_net:
            self.session.wire_session.clear()
            if was_running:
                self.tap.stop()
                self.emit_event(
                    "toast",
                    {"message": "Network changed — Connect again.", "error": False},
                )
        return _ok(settings)

    def cmd_save_format(self, args: dict[str, Any]) -> dict[str, Any]:
        return _ok(self.apply_format(args))

    def cmd_list_printers(self, _args: dict[str, Any]) -> dict[str, Any]:
        return _ok(self._printers())

    def _printers(self) -> list[dict[str, str]]:
        current = self.session.settings.printer_destination()
        choices = list_printer_choices(current)
        out = [{"label": c.label, "destination": c.destination} for c in choices]
        if current == "fake" and not any(p["destination"] == "fake" for p in out):
            out.insert(0, {"label": "fake (test)", "destination": "fake"})
        return out

    def cmd_list_print_profiles(self, _args: dict[str, Any]) -> dict[str, Any]:
        return _ok(self._profiles())

    def _profiles(self) -> list[dict[str, Any]]:
        return [
            {
                "id": p.id,
                "label": p.label,
                "builtin": p.builtin,
                "payload": p.payload,
            }
            for p in self.session.settings.list_print_profiles()
        ]

    def cmd_apply_print_profile(self, args: dict[str, Any]) -> dict[str, Any]:
        profile_id = str(args.get("profile_id") or "")
        self.session.settings.apply_print_profile(profile_id)
        dest = self.session.settings.printer_destination()
        self.session.rebuild_printer(use_fake_printer=dest == "fake")
        return _ok(self.serialize_settings())

    def cmd_save_user_print_profile(self, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name") or "").strip()
        if not name:
            return _err("Profile name is required")
        self.session.settings.save_user_print_profile(name)
        return _ok({"profiles": self._profiles(), "settings": self.serialize_settings()})

    def cmd_delete_user_print_profile(self, args: dict[str, Any]) -> dict[str, Any]:
        profile_id = str(args.get("profile_id") or "")
        self.session.settings.delete_user_print_profile(profile_id)
        return _ok({"profiles": self._profiles()})

    def cmd_list_messages(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = int(args.get("limit") or 80)
        return _ok(self.list_messages(limit))

    def cmd_get_message(self, args: dict[str, Any]) -> dict[str, Any]:
        mid = int(args["message_id"])
        msg = self.session.messages.get(mid)
        if msg is None:
            return _err(f"Message {mid} not found")
        return _ok(self._serialize_message(msg, include_body=True))

    def cmd_print_message(self, args: dict[str, Any]) -> dict[str, Any]:
        mid = int(args["message_id"])
        msg = self.session.messages.get(mid)
        if msg is None:
            return _err(f"Message {mid} not found")
        settings = self.session.settings.as_printer_settings()
        result_holder = {"result": "printed"}

        def job() -> None:
            result_holder["result"] = self.session.print_manager.print_message(
                msg, settings, is_reprint=True
            )

        if self.session.sterile.run_or_defer_acars(job):
            return _ok({"result": "deferred"})
        return _ok({"result": result_holder["result"]})

    def cmd_reprint_last(self, _args: dict[str, Any]) -> dict[str, Any]:
        result = self.actions.reprint_last()
        return _ok({"result": result})

    def cmd_test_print(self, _args: dict[str, Any]) -> dict[str, Any]:
        self.actions.test_print()
        return _ok({"ok": True})

    def cmd_feed(self, args: dict[str, Any]) -> dict[str, Any]:
        lines = args.get("lines")
        self.actions.feed(lines=int(lines) if lines is not None else None)
        return _ok({"ok": True})

    def cmd_toggle_auto_print(self, _args: dict[str, Any]) -> dict[str, Any]:
        enabled = self.actions.toggle_auto_print()
        return _ok({"auto_print": enabled})

    def cmd_connect(self, _args: dict[str, Any]) -> dict[str, Any]:
        dest = (self.session.settings.printer_destination() or "").strip()
        if not dest:
            return _err("Pick a printer in Format before connecting.")
        try:
            self.tap.start()
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            self.debug.error("connect", message=message)
            lowered = message.lower()
            if "administrator" in lowered or "elevat" in lowered:
                return _err(f"NEEDS_ELEVATION:{message}")
            return _err(message)
        status = self.build_status()
        note = self.tap.status.last_error
        msg = note or "Waiting for the aircraft to send ACARS…"
        self.emit_event("toast", {"message": msg, "error": False})
        self.emit_event("status", status)
        return _ok(status)

    def cmd_disconnect(self, _args: dict[str, Any]) -> dict[str, Any]:
        self.tap.stop()
        status = self.build_status()
        self.emit_event("toast", {"message": "Disconnected", "error": False})
        self.emit_event("status", status)
        return _ok(status)

    def cmd_refresh(self, _args: dict[str, Any]) -> dict[str, Any]:
        checked = False
        if self.tap.status.running:
            self._user_check_pending = True
            self.tap.check_now()
            checked = True
        return _ok({"checked": checked, "messages": self.list_messages(), "status": self.build_status()})

    def cmd_get_status(self, _args: dict[str, Any]) -> dict[str, Any]:
        return _ok(self.build_status())

    def cmd_simbrief_print(self, _args: dict[str, Any]) -> dict[str, Any]:
        snap = self.session.simconnect.snapshot()
        if not snap.connected:
            return _err("SimConnect not connected — cannot print OFP.")
        watcher = self.session.ensure_simbrief_watcher()
        message = watcher.print_now()
        status = self.build_status()
        self.emit_event("status", status)
        self.emit_event("toast", {"message": message, "error": False})
        return _ok({"message": message, "status": status})

    def cmd_simbrief_unlock(self, _args: dict[str, Any]) -> dict[str, Any]:
        watcher = self.session.ensure_simbrief_watcher()
        watcher.unlock(reason="manual")
        status = self.build_status()
        self.emit_event("status", status)
        msg = "OFP unlocked"
        self.emit_event("toast", {"message": msg, "error": False})
        return _ok({"message": msg, "status": status})

    def cmd_tick(self, _args: dict[str, Any]) -> dict[str, Any]:
        """One UI-timer tick: sterile/power/OFP/WX (same as Qt 1 Hz)."""
        self.tick()
        return _ok(self.build_status())

    def _background_tick_loop(self) -> None:
        while not self._tick_stop.wait(1.0):
            if self._closed:
                break
            try:
                self.tick()
            except Exception:
                self.debug.info("tick_error", error=traceback.format_exc(limit=3))

    def tick(self) -> None:
        """Sterile/power/OFP/WX pulse — safe to call from UI or background."""
        with self._tick_lock:
            self._tick_unlocked()

    def _tick_unlocked(self) -> None:
        from acars_bridge.simconnect.monitor import SimSnapshot

        snap = self.session.simconnect.snapshot()
        was_blocking = self.session.sterile.is_blocking
        was_sterile = self.session.sterile.is_sterile
        was_unpowered = self.session.sterile.is_unpowered
        was_powered = self.session.sterile.battery_on
        try:
            self.session.sterile.update_from_snapshot(snap)
        except Exception:
            pass
        now_blocking = self.session.sterile.is_blocking
        now_sterile = self.session.sterile.is_sterile
        now_unpowered = self.session.sterile.is_unpowered
        now_powered = self.session.sterile.battery_on

        if isinstance(snap, SimSnapshot) and snap.connected:
            detail = snap.detail or ""
            if detail and detail != self._last_simconnect_detail:
                self._last_simconnect_detail = detail
                self.debug.info("simconnect", detail=detail)

        if was_powered != now_powered or was_unpowered != now_unpowered:
            self.debug.info(
                "power_gate",
                was_powered=was_powered,
                now_powered=now_powered,
                blocking=now_blocking,
                battery_on=getattr(snap, "battery_on", None),
                external_power_on=getattr(snap, "external_power_on", None),
                main_bus_voltage=getattr(snap, "main_bus_voltage", None),
                apu_generator_on=getattr(snap, "apu_generator_on", None),
            )

        # Seed previous sample so the first telemetry edge is not mis-toasted.
        if self._power_was_blocking is None:
            self._power_was_blocking = now_blocking
            self._power_was_sterile = now_sterile
            self._power_was_unpowered = now_unpowered
            self._power_was_powered = now_powered
        else:
            self._emit_power_sterile_toasts(
                was_blocking=was_blocking,
                was_sterile=was_sterile,
                was_unpowered=was_unpowered,
                was_powered=was_powered,
                now_blocking=now_blocking,
                now_sterile=now_sterile,
                now_unpowered=now_unpowered,
                now_powered=now_powered,
            )
            self._power_was_blocking = now_blocking
            self._power_was_sterile = now_sterile
            self._power_was_unpowered = now_unpowered
            self._power_was_powered = now_powered

        watcher = self.session.ensure_simbrief_watcher()
        try:
            watcher.tick_local(snap)
        except Exception:
            pass
        self._schedule_simbrief_poll(watcher)
        try:
            plan = watcher.state.plan
            if (
                self.session.settings.wx_auto_enabled()
                and plan is not None
                and snap is not None
            ):
                self.session.ensure_auto_wx().consider(snap, plan)
        except Exception:
            pass
        self.emit_event("status", self.build_status())

    def _emit_power_sterile_toasts(
        self,
        *,
        was_blocking: bool,
        was_sterile: bool,
        was_unpowered: bool,
        was_powered: bool | None,
        now_blocking: bool,
        now_sterile: bool,
        now_unpowered: bool,
        now_powered: bool | None,
    ) -> None:
        del now_powered  # logged elsewhere; toast uses was_powered edge
        if was_blocking and not now_blocking:
            # Only announce "Power on" after a confirmed cold state — not the
            # first telemetry sample after "unknown / waiting for SimConnect".
            if was_unpowered and was_powered is False and not was_sterile:
                self.emit_event(
                    "toast",
                    {"message": "Power on — printing queued strips", "error": False},
                )
            else:
                self.emit_event(
                    "toast",
                    {"message": "Hold ended — printing queued strips", "error": False},
                )
        elif (
            was_unpowered
            and not now_unpowered
            and now_blocking
            and self.session.sterile.is_settling
        ):
            self.emit_event(
                "toast",
                {"message": "Power on — printing in 10 seconds", "error": False},
            )
        elif not was_sterile and now_sterile:
            agl = int(self.session.sterile.thresholds.agl_ft)
            self.emit_event(
                "toast",
                {"message": f"Sterile until {agl} ft AGL", "error": False},
            )
        elif (
            not was_unpowered
            and now_unpowered
            and self.session.sterile.battery_on is False
        ):
            self.emit_event(
                "toast",
                {"message": "Aircraft unpowered — prints queued", "error": False},
            )

    def _schedule_simbrief_poll(self, watcher: Any) -> None:
        try:
            if not watcher.needs_network_poll():
                return
        except Exception:
            return
        if self._simbrief_poll_pending or self._closed:
            return
        self._simbrief_poll_pending = True

        def _work() -> None:
            try:
                if self._closed:
                    return
                watcher.poll_network_if_due()
            except Exception:
                self.debug.info(
                    "simbrief_poll_error", error=traceback.format_exc(limit=3)
                )
            finally:
                self._simbrief_poll_pending = False

        try:
            self._simbrief_pool.submit(_work)
        except Exception:
            self._simbrief_poll_pending = False

    def cmd_debug_paste(self, _args: dict[str, Any]) -> dict[str, Any]:
        header = {
            "version": __version__,
            "data_dir": str(self.session.paths.root),
            "network": self.session.settings.acars_network().value,
            "callsign": self.session.settings.callsign() or "",
            "printer": self.session.settings.printer_destination(),
            "tap_exchanges": self.tap.status.exchanges,
            "tap_error": self.tap.status.last_error or "",
        }
        return _ok({"text": self.debug.paste_block(header=header)})

    def cmd_debug_clear(self, _args: dict[str, Any]) -> dict[str, Any]:
        self.debug.clear()
        return _ok({"cleared": True})

    def cmd_debug_folder(self, _args: dict[str, Any]) -> dict[str, Any]:
        """Open the folder that holds the support log (next to the EXE when packaged)."""
        log = self.debug.path
        folder = log.parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return _ok({"path": str(folder), "log": str(log)})

    def cmd_check_updates(self, args: dict[str, Any]) -> dict[str, Any]:
        skipped = self.session.settings.skipped_update_version()
        manual = bool(args.get("manual", True))
        try:
            release = check_for_update(skipped_version=skipped)
        except UpdateError as exc:
            if manual:
                return _err(str(exc))
            return _ok({"release": None, "can_install": can_auto_install()})
        if release is None:
            return _ok({"release": None, "can_install": can_auto_install()})
        return _ok(
            {
                "release": {
                    "version": release.version,
                    "notes": release.body,
                    "asset_url": release.download_url,
                    "html_url": release.html_url,
                    "asset_name": release.asset_name,
                },
                "can_install": can_auto_install(),
            }
        )

    def cmd_install_update(self, _args: dict[str, Any]) -> dict[str, Any]:
        """Download the latest portable EXE and schedule replace of the shell."""
        exe = current_executable()
        if exe is None:
            return _err(
                "Automatic install is only available from the Windows desktop app."
            )
        skipped = self.session.settings.skipped_update_version()
        try:
            release = check_for_update(skipped_version=skipped)
        except UpdateError as exc:
            return _err(str(exc))
        if release is None:
            return _err("No update available.")
        dest = self.session.paths.root / "updates"
        try:
            path = download_release(release, dest)
            schedule_windows_replace_and_restart(
                new_exe=path,
                current_exe=exe,
                wait_pid=shell_wait_pid(),
            )
        except UpdateError as exc:
            return _err(str(exc))
        self.debug.info(
            "update_scheduled",
            version=release.version,
            target=str(exe),
        )
        return _ok({"restarting": True, "version": release.version})

    def cmd_skip_update(self, args: dict[str, Any]) -> dict[str, Any]:
        version = str(args.get("version") or "")
        self.session.settings.set_skipped_update_version(version or None)
        return _ok({"skipped": version})

    def cmd_hotkey(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action") or "")
        mapping = {
            "reprint_last": self.cmd_reprint_last,
            "toggle_auto_print": self.cmd_toggle_auto_print,
            "test_print": self.cmd_test_print,
            "feed": self.cmd_feed,
        }
        handler = mapping.get(action)
        if handler is None:
            return _err(f"Unknown hotkey action: {action}")
        return handler(args)

    def cmd_quit(self, _args: dict[str, Any]) -> dict[str, Any]:
        self.shutdown()
        return _ok({"stopped": True})

    def cmd_drain_events(self, _args: dict[str, Any]) -> dict[str, Any]:
        return _ok(self.drain_events())

    def _companion_info(self) -> dict[str, Any]:
        s = self.session.settings
        info = {
            "enabled": s.companion_enabled(),
            "station_enabled": s.companion_station_enabled(),
            "port": s.companion_port(),
            "url": "",
            "token": "",
            "server_running": bool(
                getattr(self, "companion_server", None) and self.companion_server.running
            ),
            "station_polling": bool(
                getattr(self, "companion_poller", None) and self.companion_poller.running
            ),
            "station_error": (
                self.companion_poller.last_error
                if getattr(self, "companion_poller", None)
                else None
            ),
        }
        if s.companion_enabled():
            info["url"] = self.serialize_settings().get("companion_url") or ""
        return info

    def _enforce_station_available(self) -> str | None:
        """Probe Hoppie; if callsign is taken, force station mode off.

        Returns a user-facing reason when blocked, else None.
        """
        from acars_bridge.services.companion_guard import probe_station_callsign

        s = self.session.settings
        if not s.companion_station_enabled():
            return None
        result = probe_station_callsign(self.session)
        if result.ok:
            return None
        s.set_companion_station_enabled(False)
        try:
            self.companion_poller.stop()
        except Exception:
            pass
        reason = result.reason or "Station mode blocked."
        self.emit_event("toast", {"message": reason, "error": True})
        return reason

    def _sync_companion(self) -> str | None:
        """Start/stop companion HTTP + station poller. Returns station block reason."""
        if not hasattr(self, "companion_server"):
            return None
        s = self.session.settings
        blocked: str | None = None
        try:
            if s.companion_enabled():
                # Restart if port changed while running.
                if self.companion_server.running:
                    self.companion_server.stop()
                self.companion_server.start()
            else:
                self.companion_server.stop()
        except Exception as exc:  # noqa: BLE001
            self.debug.error("companion_server", message=str(exc))
            self.emit_event("toast", {"message": f"Companion server: {exc}", "error": True})
        try:
            if s.companion_enabled() and s.companion_station_enabled():
                blocked = self._enforce_station_available()
                if s.companion_station_enabled():
                    self.companion_poller.start()
                else:
                    self.companion_poller.stop()
            else:
                self.companion_poller.stop()
        except Exception as exc:  # noqa: BLE001
            self.debug.error("companion_poller", message=str(exc))
        return blocked

    def cmd_companion_status(self, _args: dict[str, Any]) -> dict[str, Any]:
        return _ok(self._companion_info())

    def cmd_clear_messages(self, _args: dict[str, Any]) -> dict[str, Any]:
        self.session.messages.clear_all()
        return _ok({"cleared": True, "messages": []})

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._tick_stop.set()
            thread = self._tick_thread
            if thread is not None and thread.is_alive():
                thread.join(timeout=2.0)
        except Exception:
            pass
        try:
            self._simbrief_pool.shutdown(wait=False, cancel_futures=False)
        except Exception:
            pass
        try:
            if hasattr(self, "companion_poller"):
                self.companion_poller.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "companion_server"):
                self.companion_server.stop()
        except Exception:
            pass
        try:
            self.tap.stop()
        except Exception:
            pass
        try:
            self.session.close()
        except Exception:
            pass
