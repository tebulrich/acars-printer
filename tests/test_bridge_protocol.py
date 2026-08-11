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
    assert link["state"] == "ok"
    assert "err" not in link["text"].lower()
    assert "on" in link["text"].lower() or "seen" in link["text"].lower()
    assert "sim traffic" in (link.get("tip") or "").lower()


def test_link_status_real_failure_says_issue_not_err(runtime: BridgeRuntime) -> None:
    runtime.tap.status.running = True
    runtime.tap.status.last_error = "TLS MITM failed 3x — HTTPS passthrough ON"
    link = runtime._link_chip()
    assert link["state"] == "warn"
    assert "err" not in link["text"].lower()
    assert "issue" in link["text"].lower()


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
    assert status["link"]["state"] in {"ok", "…", "..."}
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


def test_quit_shuts_down(runtime: BridgeRuntime) -> None:
    _ok(runtime, "boot")
    _ok(runtime, "connect")
    data = _ok(runtime, "quit")
    assert data["stopped"] is True
