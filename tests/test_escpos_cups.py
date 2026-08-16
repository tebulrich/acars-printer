from __future__ import annotations

from unittest.mock import MagicMock, patch

from acars_bridge.hoppie.parser import parse_response
from acars_bridge.printing.base import PrinterSettings
from acars_bridge.printing.escpos_printer import EscPosMessagePrinter
from acars_bridge.printing.formatter import ThermalMessageFormatter


def _lp_then_idle(cmd, **kwargs):
    if cmd and cmd[0] == "lpstat":
        return MagicMock(
            returncode=0,
            stdout="printer Brother_MFC is idle.  enabled\n",
            stderr="",
        )
    return MagicMock(returncode=0, stderr=b"", stdout=b"request id is Brother-1\n")


def test_cups_destination_sends_plain_text(app_session, fixture_text):
    messages = parse_response(fixture_text("cpdlc_short.txt"), "SWR14")
    app_session.ingestion.ingest(messages, auto_print=False)
    message = app_session.messages.list_recent(1)[0]
    settings = PrinterSettings(destination="cups://Brother_MFC", paper_width="80")
    body = ThermalMessageFormatter().format(message, settings)

    with patch(
        "acars_bridge.printing.escpos_printer.subprocess.run",
        side_effect=_lp_then_idle,
    ) as run:
        EscPosMessagePrinter().print(message, body, settings)

    lp_calls = [c for c in run.call_args_list if c.args[0][0] == "lp"]
    assert len(lp_calls) == 1
    args, kwargs = lp_calls[0]
    assert args[0][:3] == ["lp", "-d", "Brother_MFC"]
    assert "document-format=text/plain" in args[0]
    assert "raw" not in args[0]
    assert b"ACARS BEGIN" in kwargs["input"]
    assert b"FL360" in kwargs["input"]
    assert b"FROM" not in kwargs["input"]
    assert not kwargs["input"].startswith(b"\x1b")


def test_cups_raw_destination_sends_escpos(app_session, fixture_text):
    messages = parse_response(fixture_text("cpdlc_short.txt"), "SWR14")
    app_session.ingestion.ingest(messages, auto_print=False)
    message = app_session.messages.list_recent(1)[0]
    settings = PrinterSettings(destination="cups-raw://Thermal", paper_width="80")
    body = ThermalMessageFormatter().format(message, settings)

    with patch(
        "acars_bridge.printing.escpos_printer.subprocess.run",
        side_effect=_lp_then_idle,
    ) as run:
        EscPosMessagePrinter().print(message, body, settings)

    lp_calls = [c for c in run.call_args_list if c.args[0][0] == "lp"]
    assert len(lp_calls) == 1
    args, kwargs = lp_calls[0]
    assert args[0][:3] == ["lp", "-d", "Thermal"]
    assert "raw" in args[0]
    assert b"FL360" in kwargs["input"]
    assert b"\x1b" in kwargs["input"] or b"\x1d" in kwargs["input"]


def test_cups_surfaces_printer_fault(app_session, fixture_text):
    messages = parse_response(fixture_text("cpdlc_short.txt"), "SWR14")
    app_session.ingestion.ingest(messages, auto_print=False)
    message = app_session.messages.list_recent(1)[0]
    settings = PrinterSettings(destination="cups://Brother_MFC", paper_width="80")
    body = ThermalMessageFormatter().format(message, settings)

    def faulting(cmd, **kwargs):
        if cmd and cmd[0] == "lpstat":
            return MagicMock(
                returncode=0,
                stdout=(
                    "printer Brother_MFC now printing Brother-1.\n"
                    "\tNo suitable destination host found by cups-browsed\n"
                ),
                stderr="",
            )
        return MagicMock(returncode=0, stderr=b"", stdout=b"ok\n")

    with patch(
        "acars_bridge.printing.escpos_printer.subprocess.run",
        side_effect=faulting,
    ):
        try:
            EscPosMessagePrinter().print(message, body, settings)
            raise AssertionError("expected PrinterError")
        except Exception as exc:
            assert "No suitable destination host" in str(exc)
