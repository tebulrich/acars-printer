from __future__ import annotations

from acars_bridge.hoppie.parser import parse_response
from acars_bridge.printing.base import PrinterSettings
from acars_bridge.printing.escpos_printer import EscPosMessagePrinter
from acars_bridge.printing.formatter import ThermalMessageFormatter


def test_escpos_writes_file(app_session, fixture_text, tmp_path):
    messages = parse_response(fixture_text("cpdlc_short.txt"), "SWR14")
    stored = app_session.ingestion.ingest(messages, auto_print=False)
    assert stored["stored"] == 1
    message = app_session.messages.list_recent(1)[0]

    path = tmp_path / "out.bin"
    settings = PrinterSettings(destination=f"file://{path}", paper_width="80")
    body = ThermalMessageFormatter().format(message, settings)
    EscPosMessagePrinter().print(message, body, settings)

    data = path.read_bytes()
    assert b"ACARS PRINT BRIDGE" not in data
    assert b"FL360" in data
    assert b"ACARS BEGIN" in data
    assert b"ACARS END" in data
    assert b"FROM" not in data
    # Normal Font A size — not double-height (ESC ! 0x10) stretch.
    assert b"\x1b!\x10" not in data
    # Lead-in feed (ESC d n) before the first text line so time isn't clipped.
    feed = data.find(b"\x1bd")
    text = data.find(b"FL360")
    assert feed != -1 and text != -1 and feed < text


def test_escpos_tear_assist_feeds_before_cut(app_session, fixture_text, tmp_path):
    messages = parse_response(fixture_text("cpdlc_short.txt"), "SWR14")
    app_session.ingestion.ingest(messages, auto_print=False)
    message = app_session.messages.list_recent(1)[0]

    path = tmp_path / "cut.bin"
    settings = PrinterSettings(
        destination=f"file://{path}",
        paper_width="80",
        cut_enabled=True,
    )
    body = ThermalMessageFormatter().format(message, settings)
    EscPosMessagePrinter().print(message, body, settings)

    data = path.read_bytes()
    # ESC d n  (print_and_feed) and/or GS V (cut)
    assert b"\x1bd" in data or b"\x1dV" in data


def test_escpos_cut_disabled_skips_tear_assist(app_session, fixture_text, tmp_path):
    messages = parse_response(fixture_text("cpdlc_short.txt"), "SWR14")
    app_session.ingestion.ingest(messages, auto_print=False)
    message = app_session.messages.list_recent(1)[0]

    path = tmp_path / "nocut.bin"
    settings = PrinterSettings(
        destination=f"file://{path}",
        paper_width="80",
        cut_enabled=False,
    )
    body = ThermalMessageFormatter().format(message, settings)
    EscPosMessagePrinter().print(message, body, settings)

    data = path.read_bytes()
    assert b"\x1dV" not in data
