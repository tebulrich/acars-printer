from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from acars_bridge.config import DEFAULT_POLL_INTERVAL_SECONDS
from acars_bridge.hoppie.types import ClientMode
from acars_bridge.models.db import Database
from acars_bridge.network import (
    DEFAULT_NETWORK,
    AcarsNetwork,
    NetworkProfile,
    parse_network,
    profile_for,
)


class SettingsStore:
    def __init__(self, db: Database, key_path: Path) -> None:
        self._db = db
        self._key_path = key_path
        self._fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        if self._key_path.exists():
            return self._key_path.read_bytes().strip()
        key = Fernet.generate_key()
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        self._key_path.write_bytes(key)
        try:
            self._key_path.chmod(0o600)
        except OSError:
            pass
        return key

    def get(self, key: str, default: str | None = None) -> str | None:
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return default
        return row["value"]

    def set(self, key: str, value: str | None) -> None:
        with self._db.lock:
            if value is None:
                self._db.conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                self._db.conn.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
            self._db.conn.commit()

    def hoppie_logon(self) -> str | None:
        encrypted = self.get("hoppie_logon")
        if not encrypted:
            return None
        try:
            return self._fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            return None

    def set_hoppie_logon(self, logon: str) -> None:
        token = self._fernet.encrypt(logon.encode("utf-8")).decode("utf-8")
        self.set("hoppie_logon", token)

    def callsign(self) -> str | None:
        value = self.get("callsign")
        return value.upper() if value else None

    def set_callsign(self, callsign: str) -> None:
        self.set("callsign", callsign.strip().upper())

    def aircraft_registration(self) -> str | None:
        """Tail number for ACARS hardcopy header (e.g. D-AIXX)."""
        value = self.get("aircraft_registration")
        return value.upper() if value else None

    def set_aircraft_registration(self, registration: str) -> None:
        cleaned = registration.strip().upper()
        self.set("aircraft_registration", cleaned or None)

    def mode(self) -> ClientMode:
        # Print-bridge is tap-only; mode is always observer for stored settings.
        return ClientMode.OBSERVER

    def set_mode(self, mode: ClientMode) -> None:
        # Ignore station; always persist observer.
        self.set("client_mode", ClientMode.OBSERVER.value)

    def acars_network(self) -> AcarsNetwork:
        return parse_network(self.get("acars_network", DEFAULT_NETWORK.value))

    def set_acars_network(self, network: AcarsNetwork | str) -> None:
        self.set("acars_network", parse_network(network).value)

    def network_profile(self) -> NetworkProfile:
        return profile_for(self.acars_network())

    def hoppie_url(self) -> str:
        """Upstream connect.html URL for the selected ACARS network."""
        return self.network_profile().connect_url

    def poll_interval(self) -> int:
        raw = self.get("poll_interval", str(DEFAULT_POLL_INTERVAL_SECONDS))
        try:
            return max(45, int(raw or DEFAULT_POLL_INTERVAL_SECONDS))
        except ValueError:
            return DEFAULT_POLL_INTERVAL_SECONDS

    def auto_print(self) -> bool:
        return (self.get("auto_print", "1") or "1") in {"1", "true", "yes", "on"}

    def set_auto_print(self, enabled: bool) -> None:
        self.set("auto_print", "1" if enabled else "0")

    def auto_connect(self) -> bool:
        """Connect the ACARS tap automatically when the UI starts."""
        return (self.get("auto_connect", "1") or "1") in {"1", "true", "yes", "on"}

    def set_auto_connect(self, enabled: bool) -> None:
        self.set("auto_connect", "1" if enabled else "0")

    def check_updates(self) -> bool:
        return (self.get("check_updates", "1") or "1") in {"1", "true", "yes", "on"}

    def set_check_updates(self, enabled: bool) -> None:
        self.set("check_updates", "1" if enabled else "0")

    def skipped_update_version(self) -> str | None:
        value = (self.get("skipped_update_version") or "").strip()
        return value or None

    def set_skipped_update_version(self, version: str | None) -> None:
        if not version:
            self.set("skipped_update_version", None)
        else:
            self.set("skipped_update_version", version.lstrip("vV").strip())

    def printer_destination(self) -> str:
        return self.get("printer_destination", "console") or "console"

    def set_printer_destination(self, destination: str) -> None:
        self.set("printer_destination", destination)

    def paper_width(self) -> str:
        value = self.get("paper_width", "80") or "80"
        return "58" if value == "58" else "80"

    def set_paper_width(self, width: str) -> None:
        self.set("paper_width", "58" if str(width) == "58" else "80")

    def ui_scale(self) -> float:
        """Fixed at 100% — OS DPI only."""
        return 1.0

    def set_ui_scale(self, scale: float | str) -> None:
        # Kept for older settings DBs; UI scale is no longer configurable.
        self.set("ui_scale", "1.00")

    def cut_enabled(self) -> bool:
        # Default on: thermal POS needs feed-to-tear-bar after each receipt.
        return (self.get("cut_enabled", "1") or "1") in {"1", "true", "yes", "on"}

    def set_cut_enabled(self, enabled: bool) -> None:
        self.set("cut_enabled", "1" if enabled else "0")

    def print_font(self) -> str:
        value = (self.get("print_font", "a") or "a").strip().lower()
        return "b" if value == "b" else "a"

    def set_print_font(self, font: str) -> None:
        self.set("print_font", "b" if str(font).strip().lower() == "b" else "a")

    def print_bold(self) -> bool:
        # Default off — bold Consolas on thermal looks too heavy vs airline strips.
        return (self.get("print_bold", "0") or "0") in {"1", "true", "yes", "on"}

    def set_print_bold(self, enabled: bool) -> None:
        self.set("print_bold", "1" if enabled else "0")

    def print_render_mode(self) -> str:
        value = (self.get("print_render_mode") or "").strip().lower()
        if value in {"bitmap", "native"}:
            return value
        # Default to exact pixel sizing — built-in fonts cannot go below 1×.
        return "bitmap"

    def set_print_render_mode(self, mode: str) -> None:
        value = str(mode).strip().lower()
        self.set("print_render_mode", "bitmap" if value == "bitmap" else "native")

    def print_char_width(self) -> int:
        raw = self.get("print_char_width")
        if raw is None:
            # Migrate old print_size presets.
            legacy = (self.get("print_size", "normal") or "normal").strip().lower()
            return 2 if legacy in {"wide", "large"} else 1
        try:
            return max(1, min(8, int(raw)))
        except ValueError:
            return 1

    def set_print_char_width(self, width: int | str) -> None:
        try:
            value = int(width)
        except (TypeError, ValueError):
            value = 1
        self.set("print_char_width", str(max(1, min(8, value))))

    def print_char_height(self) -> int:
        raw = self.get("print_char_height")
        if raw is None:
            legacy = (self.get("print_size", "normal") or "normal").strip().lower()
            return 2 if legacy in {"tall", "large"} else 1
        try:
            return max(1, min(8, int(raw)))
        except ValueError:
            return 1

    def set_print_char_height(self, height: int | str) -> None:
        try:
            value = int(height)
        except (TypeError, ValueError):
            value = 1
        self.set("print_char_height", str(max(1, min(8, value))))

    def print_line_spacing_dots(self) -> int | None:
        raw = self.get("print_line_spacing_dots")
        if raw is None:
            # Migrate old named presets.
            legacy = (self.get("print_line_spacing", "default") or "default").strip().lower()
            mapping = {"tight": 24, "normal": 30, "loose": 40}
            return mapping.get(legacy)
        value = str(raw).strip().lower()
        if value in {"", "default", "auto", "-1"}:
            return None
        try:
            dots = int(value)
        except ValueError:
            return None
        if dots <= 0:
            return None
        return max(1, min(255, dots))

    def set_print_line_spacing_dots(self, dots: int | str | None) -> None:
        if dots is None or str(dots).strip().lower() in {"", "default", "auto", "0", "-1"}:
            self.set("print_line_spacing_dots", "default")
            return
        try:
            value = int(dots)
        except (TypeError, ValueError):
            self.set("print_line_spacing_dots", "default")
            return
        if value <= 0:
            self.set("print_line_spacing_dots", "default")
        else:
            self.set("print_line_spacing_dots", str(max(1, min(255, value))))

    def print_glyph_px(self) -> int:
        raw = self.get("print_glyph_px", "28")
        try:
            return max(8, min(64, int(raw or 28)))
        except ValueError:
            return 28

    def set_print_glyph_px(self, px: int | str) -> None:
        try:
            value = int(px)
        except (TypeError, ValueError):
            value = 28
        self.set("print_glyph_px", str(max(8, min(64, value))))

    def print_line_gap_px(self) -> int:
        raw = self.get("print_line_gap_px", "2")
        try:
            return max(0, min(32, int(raw or 2)))
        except ValueError:
            return 2

    def set_print_line_gap_px(self, px: int | str) -> None:
        try:
            value = int(px)
        except (TypeError, ValueError):
            value = 2
        self.set("print_line_gap_px", str(max(0, min(32, value))))

    def print_columns(self) -> int | None:
        """Manual wrap width; None = auto from paper width + font."""
        raw = (self.get("print_columns") or "").strip()
        if not raw or raw.lower() in {"auto", "0"}:
            return None
        try:
            cols = int(raw)
        except ValueError:
            return None
        return max(16, min(80, cols))

    def set_print_columns(self, columns: int | str | None) -> None:
        if columns is None or str(columns).strip().lower() in {"", "auto", "0"}:
            self.set("print_columns", None)
            return
        try:
            cols = int(columns)
        except (TypeError, ValueError):
            self.set("print_columns", None)
            return
        self.set("print_columns", str(max(16, min(80, cols))))

    def print_lead_in(self) -> int:
        # ~2 lines ≈ 1.5 cm on a typical POS-80; 3 was closer to ~2 cm.
        raw = self.get("print_lead_in", "2")
        try:
            return max(0, min(12, int(raw or 2)))
        except ValueError:
            return 2

    def set_print_lead_in(self, lines: int | str) -> None:
        try:
            value = int(lines)
        except (TypeError, ValueError):
            value = 2
        self.set("print_lead_in", str(max(0, min(12, value))))

    def print_tear_feed(self) -> int:
        raw = self.get("print_tear_feed", "6")
        try:
            return max(0, min(16, int(raw or 6)))
        except ValueError:
            return 6

    def set_print_tear_feed(self, lines: int | str) -> None:
        try:
            value = int(lines)
        except (TypeError, ValueError):
            value = 6
        self.set("print_tear_feed", str(max(0, min(16, value))))

    def as_printer_settings(self, destination: str | None = None) -> "PrinterSettings":
        from acars_bridge.printing.base import PrinterSettings

        return PrinterSettings(
            destination=destination or self.printer_destination(),
            paper_width=self.paper_width(),
            cut_enabled=self.cut_enabled(),
            character_width_override=self.print_columns(),
            aircraft_registration=self.aircraft_registration(),
            font=self.print_font(),  # type: ignore[arg-type]
            bold=self.print_bold(),
            render_mode=self.print_render_mode(),  # type: ignore[arg-type]
            char_width=self.print_char_width(),
            char_height=self.print_char_height(),
            line_spacing_dots=self.print_line_spacing_dots(),
            glyph_px=self.print_glyph_px(),
            line_gap_px=self.print_line_gap_px(),
            lead_in_lines=self.print_lead_in(),
            tear_feed_lines=self.print_tear_feed(),
        )

    # ACARS types exposed in Settings checkboxes (single printer; mute only).
    PRINTABLE_TYPE_CHOICES: tuple[str, ...] = ("cpdlc", "telex", "inforeq")
    _PRINTABLE_TYPES_DEFAULT = "cpdlc,telex,inforeq"

    def printable_types(self) -> set[str]:
        raw = self.get("printable_types", self._PRINTABLE_TYPES_DEFAULT)
        if raw is None:
            raw = self._PRINTABLE_TYPES_DEFAULT
        return {part.strip().lower() for part in raw.split(",") if part.strip()}

    def set_printable_types(self, types: list[str] | set[str] | tuple[str, ...]) -> None:
        allowed = set(self.PRINTABLE_TYPE_CHOICES)
        cleaned = sorted(
            {
                part.strip().lower()
                for part in types
                if isinstance(part, str) and part.strip().lower() in allowed
            }
        )
        self.set("printable_types", ",".join(cleaned))

    def next_downlink_min(self) -> int:
        raw = self.get("next_downlink_min", "1") or "1"
        try:
            current = int(raw)
        except ValueError:
            current = 1
        self.set("next_downlink_min", str(current + 1))
        return current

    # --- SimBrief ---

    def simbrief_user(self) -> str | None:
        value = (self.get("simbrief_user") or "").strip()
        return value or None

    def set_simbrief_user(self, user: str) -> None:
        cleaned = user.strip()
        self.set("simbrief_user", cleaned or None)

    def simbrief_enabled(self) -> bool:
        return (self.get("simbrief_enabled", "0") or "0") in {"1", "true", "yes", "on"}

    def set_simbrief_enabled(self, enabled: bool) -> None:
        self.set("simbrief_enabled", "1" if enabled else "0")

    OFP_TICKET_CHOICES: tuple[str, ...] = (
        "flight_plan",
        "takeoff_data",
        "loadsheet_prelim",
        "loadsheet_final",
    )
    _OFP_TICKETS_DEFAULT = (
        "flight_plan,takeoff_data,loadsheet_prelim,loadsheet_final"
    )

    def simbrief_ofp_tickets(self) -> set[str]:
        raw = self.get("simbrief_ofp_tickets", self._OFP_TICKETS_DEFAULT)
        if raw is None:
            raw = self._OFP_TICKETS_DEFAULT
        allowed = set(self.OFP_TICKET_CHOICES)
        return {
            part.strip().lower()
            for part in raw.split(",")
            if part.strip().lower() in allowed
        }

    def set_simbrief_ofp_tickets(
        self, tickets: list[str] | set[str] | tuple[str, ...]
    ) -> None:
        allowed = set(self.OFP_TICKET_CHOICES)
        cleaned = sorted(
            {
                part.strip().lower()
                for part in tickets
                if isinstance(part, str) and part.strip().lower() in allowed
            }
        )
        self.set("simbrief_ofp_tickets", ",".join(cleaned))

    def simbrief_ofp_ticket_enabled(self, ticket_type: str) -> bool:
        return ticket_type.strip().lower() in self.simbrief_ofp_tickets()

    def hotkeys_enabled(self) -> bool:
        return (self.get("hotkeys_enabled", "1") or "1") in {"1", "true", "yes", "on"}

    def set_hotkeys_enabled(self, enabled: bool) -> None:
        self.set("hotkeys_enabled", "1" if enabled else "0")

    HOTKEY_ACTIONS: tuple[str, ...] = (
        "reprint_last",
        "toggle_auto_print",
        "test_print",
        "feed",
    )
    _HOTKEY_DEFAULTS: dict[str, str] = {
        "reprint_last": "Ctrl+Shift+R",
        "toggle_auto_print": "Ctrl+Shift+A",
        "test_print": "Ctrl+Shift+T",
        "feed": "Ctrl+Shift+F",
    }

    def hotkey_bindings(self) -> dict[str, str]:
        import json

        out = dict(self._HOTKEY_DEFAULTS)
        raw = self.get("hotkey_bindings")
        if not raw:
            return out
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return out
        if not isinstance(data, dict):
            return out
        for key in self.HOTKEY_ACTIONS:
            if key not in data:
                continue
            value = data[key]
            if value is None:
                out[key] = ""
            else:
                out[key] = str(value).strip()
        return out

    def set_hotkey_bindings(self, bindings: dict[str, str]) -> None:
        import json

        cleaned: dict[str, str] = {}
        for key in self.HOTKEY_ACTIONS:
            if key not in bindings:
                cleaned[key] = self._HOTKEY_DEFAULTS[key]
                continue
            cleaned[key] = str(bindings.get(key) or "").strip()
        self.set("hotkey_bindings", json.dumps(cleaned, sort_keys=True))

    def hotkey_sequence(self, action: str) -> str:
        key = action.strip().lower()
        return self.hotkey_bindings().get(key, self._HOTKEY_DEFAULTS.get(key, ""))

    def set_hotkey_sequence(self, action: str, sequence: str) -> None:
        key = action.strip().lower()
        if key not in self.HOTKEY_ACTIONS:
            return
        bindings = self.hotkey_bindings()
        bindings[key] = (sequence or "").strip()
        self.set_hotkey_bindings(bindings)

    def simbrief_post_landing_grace_seconds(self) -> int:
        raw = self.get("simbrief_post_landing_grace_seconds", "600")
        try:
            return max(60, min(7200, int(raw or 600)))
        except ValueError:
            return 600

    def set_simbrief_post_landing_grace_seconds(self, seconds: int | str) -> None:
        try:
            value = int(seconds)
        except (TypeError, ValueError):
            value = 600
        self.set("simbrief_post_landing_grace_seconds", str(max(60, min(7200, value))))

    def simbrief_last_ofp_id(self) -> str | None:
        value = (self.get("simbrief_last_ofp_id") or "").strip()
        return value or None

    def set_simbrief_last_ofp_id(self, ofp_id: str | None) -> None:
        if not ofp_id:
            self.set("simbrief_last_ofp_id", None)
        else:
            self.set("simbrief_last_ofp_id", ofp_id)

    def simbrief_lock_state(self) -> str | None:
        value = self.get("simbrief_lock_state")
        return value if value else None

    def set_simbrief_lock_state(self, blob: str | None) -> None:
        self.set("simbrief_lock_state", blob)

    # --- Sterile cockpit (mutes all thermal printing) ---

    _STERILE_AGL_CHOICES = (
        1000,
        1500,
        2000,
        2500,
        3000,
        4000,
        5000,
        6000,
        7000,
        8000,
        9000,
        10000,
    )

    def sterile_agl_ft(self) -> int:
        """Mute printing while airborne below this AGL (ft)."""
        raw = self.get("sterile_agl_ft", "1500")
        try:
            value = int(raw or 1500)
        except ValueError:
            return 1500
        if value in self._STERILE_AGL_CHOICES:
            return value
        # Snap to nearest allowed choice.
        return min(self._STERILE_AGL_CHOICES, key=lambda choice: abs(choice - value))

    def set_sterile_agl_ft(self, feet: int | str) -> None:
        try:
            value = int(feet)
        except (TypeError, ValueError):
            value = 1500
        if value not in self._STERILE_AGL_CHOICES:
            value = min(self._STERILE_AGL_CHOICES, key=lambda choice: abs(choice - value))
        self.set("sterile_agl_ft", str(value))

    @classmethod
    def sterile_agl_choices(cls) -> tuple[int, ...]:
        return cls._STERILE_AGL_CHOICES

    def print_when_powered(self) -> bool:
        """When on, queue prints until SimConnect reports aircraft electrical power."""
        return (self.get("print_when_powered", "0") or "0") in {
            "1",
            "true",
            "yes",
            "on",
        }

    def set_print_when_powered(self, enabled: bool) -> None:
        self.set("print_when_powered", "1" if enabled else "0")
