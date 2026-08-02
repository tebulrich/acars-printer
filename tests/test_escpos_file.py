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
    assert b"ACARS PRINT BRIDGE" in data
    assert b"FL360" in data
