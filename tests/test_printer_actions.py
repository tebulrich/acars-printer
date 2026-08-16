from __future__ import annotations

import pytest

from acars_bridge.hoppie.parser import parse_response
from acars_bridge.services.actions import ActionError, PrinterActions


def test_reprint_last_after_successful_print(app_session, fixture_text) -> None:
    messages = parse_response(fixture_text("cpdlc_short.txt"), "SWR14")
    assert app_session.ingestion.ingest(messages)["printed"] == 1
    actions = PrinterActions(app_session)
    result = actions.reprint_last()
    assert result == "printed"
    printer = app_session.print_manager._printer
    assert len(printer.printed) == 2
    assert printer.printed[0][0] == printer.printed[1][0]


def test_reprint_last_raises_when_nothing_printed(app_session) -> None:
    actions = PrinterActions(app_session)
    with pytest.raises(ActionError, match="No printed"):
        actions.reprint_last()


def test_toggle_auto_print(app_session) -> None:
    actions = PrinterActions(app_session)
    assert app_session.settings.auto_print() is True
    assert actions.toggle_auto_print() is False
    assert app_session.settings.auto_print() is False
    assert actions.set_auto_print(True) is True
    assert app_session.settings.auto_print() is True


def test_test_print_action(app_session) -> None:
    actions = PrinterActions(app_session)
    actions.test_print()
    printer = app_session.print_manager._printer
    assert len(printer.printed) == 1
    assert "ACARS BEGIN" in printer.printed[0][1]


def test_feed_on_fake_printer(app_session) -> None:
    actions = PrinterActions(app_session)
    actions.feed()
    printer = app_session.print_manager._printer
    assert printer.feed_count == 1
