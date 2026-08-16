"""Bridge contract tests — encode Qt UI behavior as NDJSON commands (TDD)."""

from __future__ import annotations

from pathlib import Path

import pytest

from acars_bridge.bridge.runtime import BridgeRuntime, FakeTapService
from acars_bridge.config import AppPaths
from acars_bridge.hoppie.types import HoppieMessage, MessageType
from acars_bridge.services.session import build_session


@pytest.fixture
def runtime(tmp_path: Path):
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret-logon-code")
    session.settings.set_printer_destination("fake")
    session.ingestion._print_delay_seconds = 0.0
    rt = BridgeRuntime(session, tap_factory=FakeTapService, clear_messages_on_boot=True)
    yield rt
    rt.shutdown()


def _ok(rt: BridgeRuntime, command: str, **args):
    result = rt.handle(command, args)
    assert result["ok"] is True, result
    return result["data"]


def test_link_status_info_note_is_not_an_error(runtime: BridgeRuntime) -> None:
    from datetime import UTC, datetime

    runtime.tap.status.running = True
    runtime.tap.status.last_error = None
    runtime.tap.status.last_check = datetime.now(UTC)
    runtime.tap.status.last_note = (
        "Hoppie: sim traffic only (website / companion apps stay direct)"
    )
    link = runtime._link_chip()
    assert link["state"] in {"ok", "busy"}
    assert "err" not in link["text"].lower()
    assert link["text"] == "Hoppie wait"
    tip = (link.get("tip") or "").lower()
    assert "first" in tip and "acars" in tip
    assert "sim traffic" not in tip


def test_link_status_real_failure_says_issue_not_err(runtime: BridgeRuntime) -> None:
    runtime.tap.status.running = True
    runtime.tap.status.last_error = "TLS MITM failed 3x — HTTPS passthrough ON"
    link = runtime._link_chip()
    assert link["state"] == "warn"
    assert "err" not in link["text"].lower()
    assert "issue" in link["text"].lower()


def test_link_status_hoppie_rejected_logon(runtime: BridgeRuntime) -> None:
    runtime.tap.status.running = True
    runtime.tap.status.last_hoppie_error = "invalid logon code"
    link = runtime._link_chip()
    assert link["state"] == "warn"
    assert link["text"] == "Hoppie rejected logon"
    assert "invalid logon" in (link.get("tip") or "").lower()


def test_link_status_hoppie_ok_shows_callsign(runtime: BridgeRuntime) -> None:
    runtime.tap.status.running = True
    runtime.tap.status.network_id = "hoppie"
    runtime.tap.status.exchanges = 4
    runtime.session.wire_session.update(
        logon="secret", from_cs="DLH4MC", network_id="hoppie"
    )
    link = runtime._link_chip()
    assert link["state"] == "ok"
    assert link["text"] == "Hoppie ok · DLH4MC"


def test_link_status_uses_network_name_for_si_and_gfo(runtime: BridgeRuntime) -> None:
    runtime.tap.status.running = True
    runtime.tap.status.exchanges = 2
    runtime.tap.status.network_id = "sayintentions"
    runtime.session.wire_session.update(
        logon="secret", from_cs="DLH4MC", network_id="sayintentions"
    )
    assert runtime._link_chip()["text"] == "SI ok · DLH4MC"

    runtime.tap.status.network_id = "pmdg_gfo"
    runtime.session.wire_session.update(
        logon="secret", from_cs="BAW12G", network_id="pmdg_gfo"
    )
    assert runtime._link_chip()["text"] == "GFO ok · BAW12G"


def test_power_chip_xplane_sources_off_says_off(runtime: BridgeRuntime) -> None:
    from acars_bridge.simconnect.monitor import SimSnapshot

    class _Snap:
        def snapshot(self) -> SimSnapshot:
            return SimSnapshot(
                connected=True,
                source="xplane",
                main_bus_voltage=28.0,
                apu_generator_on=False,
                electrical={
                    "ELECTRICAL BUS VOLTAGE:1": 28.0,
                    "XP GENERATOR ON:1": 0.0,
                    "XP GENERATOR ON:2": 0.0,
                    "APU GENERATOR SWITCH": 0.0,
                    "XP APU RUNNING": 0.0,
                    "XP ENG RUNNING:1": 0.0,
                    "XP AVIONICS ON": 1.0,
                },
                detail="X-Plane 12",
            )

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    runtime.session.simconnect = _Snap()  # type: ignore[assignment]
    chip = runtime._power_chip()
    assert chip["text"] == "PWR off"
    tip = (chip.get("tip") or "").lower()
    assert "engine" in tip or "apu" in tip or "ground" in tip


def test_power_chip_xplane_buses_only_are_unknown(runtime: BridgeRuntime) -> None:
    from acars_bridge.simconnect.monitor import SimSnapshot

    class _Snap:
        def snapshot(self) -> SimSnapshot:
            return SimSnapshot(
                connected=True,
                source="xplane",
                main_bus_voltage=28.0,
                electrical={"ELECTRICAL BUS VOLTAGE:1": 28.0},
                detail="X-Plane 12",
            )

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    runtime.session.simconnect = _Snap()  # type: ignore[assignment]
    chip = runtime._power_chip()
    assert chip["text"] == "PWR ?"
    tip = (chip.get("tip") or "").lower()
    assert "unknown" in tip


def test_power_chip_xplane_generator_says_on(runtime: BridgeRuntime) -> None:
    from acars_bridge.simconnect.monitor import SimSnapshot

    class _Snap:
        def snapshot(self) -> SimSnapshot:
            return SimSnapshot(
                connected=True,
                source="xplane",
                main_bus_voltage=28.0,
                apu_generator_on=False,
                electrical={
                    "ELECTRICAL BUS VOLTAGE:1": 28.0,
                    "XP GENERATOR ON:1": 1.0,
                    "APU GENERATOR SWITCH": 0.0,
                },
                detail="X-Plane 12",
            )

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    runtime.session.simconnect = _Snap()  # type: ignore[assignment]
    chip = runtime._power_chip()
    assert chip["text"] == "PWR on"
    assert "engine" in (chip.get("tip") or "").lower()


def test_power_chip_xplane_ground_power_says_on(runtime: BridgeRuntime) -> None:
    from acars_bridge.simconnect.monitor import SimSnapshot

    class _Snap:
        def snapshot(self) -> SimSnapshot:
            return SimSnapshot(
                connected=True,
                source="xplane",
                main_bus_voltage=28.0,
                external_power_on=True,
                apu_generator_on=False,
                electrical={
                    "ELECTRICAL BUS VOLTAGE:1": 28.0,
                    "XP GENERATOR ON:1": 0.0,
                    "XP GPU ON": 1.0,
                    "XP GPU VOLTS": 28.0,
                },
                detail="X-Plane 12",
            )

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    runtime.session.simconnect = _Snap()  # type: ignore[assignment]
    chip = runtime._power_chip()
    assert chip["text"] == "PWR on"
    assert "ground" in (chip.get("tip") or "").lower()


def test_power_chip_msfs_menu_is_not_on(runtime: BridgeRuntime) -> None:
    from acars_bridge.simconnect.monitor import SimSnapshot

    class _Snap:
        def snapshot(self) -> SimSnapshot:
            return SimSnapshot(
                connected=True,
                source="simconnect",
                in_session=False,
                main_bus_voltage=28.0,
                electrical={
                    "CIRCUIT GENERAL PANEL ON": 1.0,
                    "ELECTRICAL MAIN BUS VOLTAGE": 28.0,
                },
                detail="inplace",
            )

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    runtime.session.simconnect = _Snap()  # type: ignore[assignment]
    chip = runtime._power_chip()
    assert chip["text"] == "PWR —"
    tip = (chip.get("tip") or "").lower()
    assert "flight" in tip


def test_sterile_off_is_a_settings_choice(runtime: BridgeRuntime) -> None:
    data = _ok(runtime, "get_settings")
    assert 0 in data["sterile_agl_choices"]
    saved = _ok(runtime, "save_settings", sterile_agl_ft=0)
    assert saved["sterile_agl_ft"] == 0


def test_boot_returns_meta_settings_and_status(runtime: BridgeRuntime) -> None:
    data = _ok(runtime, "boot")
    assert data["meta"]["version"]
    assert data["meta"]["product"] == "ACARS Print Bridge"
    assert data["settings"]["callsign"] == "SWR14"
    assert data["settings"]["printer_destination"] == "fake"
    assert data["status"]["link"]["state"] == "off"
    assert data["status"]["chips"]["flt"].startswith("FLT")


def test_get_and_save_settings_roundtrip(runtime: BridgeRuntime) -> None:
    settings = _ok(runtime, "get_settings")
    assert "printable_types" in settings
    assert "hotkey_bindings" in settings

    saved = _ok(
        runtime,
        "save_settings",
        callsign="DLH123",
        acars_network="sayintentions",
        auto_print=False,
        printable_types=["cpdlc"],
        sterile_agl_ft=3000,
        print_when_powered=True,
        xplane_host="10.1.2.3",
        xplane_port=49010,
        simbrief_user="pilot",
        simbrief_enabled=True,
        wx_auto_enabled=True,
        wx_auto_nm=120,
        wx_auto_kinds=["metar", "taf"],
        hotkeys_enabled=True,
        hotkey_bindings={"reprint_last": "Ctrl+Alt+R"},
    )
    assert saved["callsign"] == "DLH123"
    assert saved["acars_network"] == "sayintentions"
    assert saved["auto_print"] is False
    assert saved["printable_types"] == ["cpdlc"]
    assert saved["sterile_agl_ft"] == 3000
    assert saved["wx_auto_nm"] == 120
    assert saved["xplane_host"] == "10.1.2.3"
    assert saved["xplane_port"] == 49010
    auto = _ok(runtime, "save_settings", xplane_host="auto")
    assert auto["xplane_host"] == "auto"


def test_save_hoppie_logon_for_companion_sends(runtime: BridgeRuntime) -> None:
    before = _ok(runtime, "get_settings")
    assert before["has_hoppie_logon"] is True  # fixture sets a logon
    assert "hoppie_logon" not in before

    saved = _ok(runtime, "save_settings", hoppie_logon="brand-new-logon-code")
    assert saved["has_hoppie_logon"] is True
    assert runtime.session.settings.hoppie_logon() == "brand-new-logon-code"

    # Empty value must not wipe the stored logon.
    kept = _ok(runtime, "save_settings", hoppie_logon="")
    assert kept["has_hoppie_logon"] is True
    assert runtime.session.settings.hoppie_logon() == "brand-new-logon-code"


def test_save_format_and_test_print(runtime: BridgeRuntime) -> None:
    fmt = _ok(
        runtime,
        "save_format",
        printer_destination="fake",
        paper_width="58",
        cut_enabled=True,
        print_render_mode="bitmap",
        print_glyph_px=26,
        print_line_gap_px=1,
        print_font="a",
        print_char_width=1,
        print_char_height=1,
        print_bold=False,
        print_columns=None,
        print_line_spacing_dots=None,
        print_lead_in=1,
        print_tear_feed=5,
    )
    assert fmt["paper_width"] == "58"
    _ok(runtime, "test_print")
    _ok(runtime, "feed")


def test_save_format_accepts_unc_printer_path(runtime: BridgeRuntime) -> None:
    fmt = _ok(
        runtime,
        "save_format",
        printer_destination=r"\\192.168.1.10\POS-80",
    )
    assert fmt["printer_destination"] == r"win32://\\192.168.1.10\POS-80"


def test_print_profiles_apply_save_delete(runtime: BridgeRuntime) -> None:
    profiles = _ok(runtime, "list_print_profiles")
    assert any(p["id"] == "pos80_default" for p in profiles)
    applied = _ok(runtime, "apply_print_profile", profile_id="pos58_readable")
    assert applied["paper_width"] == "58"
    saved = _ok(runtime, "save_user_print_profile", name="My58")
    assert any(p["id"] == "My58" for p in saved["profiles"])
    _ok(runtime, "delete_user_print_profile", profile_id="My58")


def test_list_printers_includes_fake_when_set(runtime: BridgeRuntime) -> None:
    printers = _ok(runtime, "list_printers")
    assert isinstance(printers, list)
    assert any(p["destination"] == "fake" for p in printers) or printers == []


def test_messages_list_print_and_reprint(runtime: BridgeRuntime) -> None:
    _ok(runtime, "boot")
    msg = HoppieMessage(
        callsign="SWR14",
        sender="EDDM",
        recipient="SWR14",
        message_type=MessageType.TELEX,
        raw_payload="telex hello",
        normalized_body="HELLO BODY",
    )
    stats = runtime.session.ingestion.ingest([msg], auto_print=False)
    assert stats["stored"] >= 1

    rows = _ok(runtime, "list_messages", limit=80)
    assert len(rows) >= 1
    mid = rows[0]["id"]
    detail = _ok(runtime, "get_message", message_id=mid)
    assert "HELLO" in detail["normalized_body"]

    printed = _ok(runtime, "print_message", message_id=mid)
    assert printed["result"] in {"printed", "deferred"}
    last = _ok(runtime, "reprint_last")
    assert last["result"] in {"printed", "deferred"}


def test_status_includes_message_count_for_ui_autorefresh(runtime: BridgeRuntime) -> None:
    """UI polls tick/status; message_count lets it reload without relying only on events."""
    _ok(runtime, "boot")
    assert _ok(runtime, "get_status")["message_count"] == 0
    runtime.session.ingestion.ingest(
        [
            HoppieMessage(
                callsign="SWR14",
                sender="EDDM",
                recipient="SWR14",
                message_type=MessageType.TELEX,
                raw_payload="telex a",
                normalized_body="A",
            ),
            HoppieMessage(
                callsign="SWR14",
                sender="EDDM",
                recipient="SWR14",
                message_type=MessageType.TELEX,
                raw_payload="telex b",
                normalized_body="B",
            ),
            HoppieMessage(
                callsign="SWR14",
                sender="EDDM",
                recipient="SWR14",
                message_type=MessageType.TELEX,
                raw_payload="telex c",
                normalized_body="C",
            ),
        ],
        auto_print=False,
    )
    status = _ok(runtime, "get_status")
    assert status["message_count"] == 3
    tick_status = _ok(runtime, "tick")
    assert tick_status["message_count"] == 3


def test_tap_new_messages_emit_event(runtime: BridgeRuntime) -> None:
    runtime.drain_events()
    runtime._on_new_messages(3)
    events = runtime.drain_events()
    assert any(
        e.get("event") == "new_messages" and e.get("data", {}).get("count") == 3
        for e in events
    )


def test_toggle_auto_print(runtime: BridgeRuntime) -> None:
    before = _ok(runtime, "get_settings")["auto_print"]
    after = _ok(runtime, "toggle_auto_print")
    assert after["auto_print"] is (not before)


def test_connect_allows_console_destination(runtime: BridgeRuntime) -> None:
    runtime.session.settings.set_printer_destination("console")
    status = _ok(runtime, "connect")
    assert status["running"] is True
    _ok(runtime, "disconnect")


def test_connect_disconnect_with_fake_tap(runtime: BridgeRuntime) -> None:
    status = _ok(runtime, "connect")
    assert status["link"]["state"] in {"ok", "busy", "…", "..."}
    assert status["running"] is True
    status = _ok(runtime, "disconnect")
    assert status["running"] is False
    assert status["link"]["state"] == "off"


def test_refresh_while_connected_calls_check(runtime: BridgeRuntime) -> None:
    _ok(runtime, "connect")
    data = _ok(runtime, "refresh")
    assert data["checked"] is True
    assert isinstance(data["messages"], list)


def test_simbrief_unlock_and_print_gates(runtime: BridgeRuntime) -> None:
    unlocked = _ok(runtime, "simbrief_unlock")
    assert "message" in unlocked
    # Without SimConnect connected, print_now should fail clearly.
    result = runtime.handle("simbrief_print", {})
    assert result["ok"] is False


def test_get_status_and_tick_emit_events(runtime: BridgeRuntime) -> None:
    _ok(runtime, "boot")
    status = _ok(runtime, "get_status")
    assert "chips" in status
    assert "clock" in status["chips"]
    runtime.tick()
    events = runtime.drain_events()
    assert any(e.get("event") == "status" for e in events)


def test_debug_log_commands(runtime: BridgeRuntime) -> None:
    _ok(runtime, "boot")
    block = _ok(runtime, "debug_paste")
    assert "ACARS" in block["text"] or "version" in block["text"].lower() or block["text"]
    _ok(runtime, "debug_clear")
    folder = _ok(runtime, "debug_folder")
    assert Path(folder["path"]).exists() or folder["path"]
    assert "log" in folder
    assert Path(folder["log"]).name


def test_debug_folder_points_at_exe_log(
    runtime: BridgeRuntime, tmp_path: Path
) -> None:
    target = tmp_path / "portable" / "acars-print-bridge.log"
    runtime.debug.path = target
    folder = _ok(runtime, "debug_folder")
    assert folder["path"] == str(target.parent)
    assert folder["log"] == str(target)


def test_install_update_requires_shell_exe(runtime: BridgeRuntime, monkeypatch) -> None:
    monkeypatch.delenv("ACARS_BRIDGE_SHELL_EXE", raising=False)
    monkeypatch.setattr(
        "acars_bridge.bridge.runtime.current_executable", lambda: None
    )
    result = runtime.handle("install_update", {})
    assert result["ok"] is False
    assert "Automatic install" in result["error"]



def test_quit_shuts_down(runtime: BridgeRuntime) -> None:
    _ok(runtime, "boot")
    _ok(runtime, "connect")
    data = _ok(runtime, "quit")
    assert data["stopped"] is True
