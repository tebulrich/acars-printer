from __future__ import annotations

from acars_bridge.hoppie.parser import parse_response
from acars_bridge.printing.fake_printer import FakeMessagePrinter


def test_stores_and_prints_once(app_session, fixture_text):
    messages = parse_response(fixture_text("cpdlc_short.txt"), "SWR14")
    stats = app_session.ingestion.ingest(messages)
    assert stats["printed"] == 1
    assert app_session.db.conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"] == 1
    assert app_session.db.conn.execute("SELECT COUNT(*) AS c FROM print_jobs").fetchone()["c"] == 1

    stats2 = app_session.ingestion.ingest(messages)
    assert stats2["duplicates"] == 1
    assert app_session.db.conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"] == 1
    assert app_session.db.conn.execute("SELECT COUNT(*) AS c FROM print_jobs").fetchone()["c"] == 1


def test_disabled_type_stored_not_printed(app_session, fixture_text):
    app_session.settings.set("printable_types", "telex")
    messages = parse_response(fixture_text("cpdlc_short.txt"), "SWR14")
    stats = app_session.ingestion.ingest(messages)
    assert stats["stored"] == 1
    assert app_session.db.conn.execute("SELECT COUNT(*) AS c FROM print_jobs").fetchone()["c"] == 0


def test_printer_failure_keeps_message(app_session, fixture_text):
    printer = app_session.print_manager._printer
    assert isinstance(printer, FakeMessagePrinter)
    printer.should_fail = True
    messages = parse_response(fixture_text("cpdlc_short.txt"), "SWR14")
    stats = app_session.ingestion.ingest(messages)
    assert stats["failed_prints"] == 1
    row = app_session.db.conn.execute("SELECT status FROM print_jobs").fetchone()
    assert row["status"] == "failed"
