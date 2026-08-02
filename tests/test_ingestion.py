from __future__ import annotations

from acars_bridge.hoppie.parser import parse_response
from acars_bridge.hoppie.types import HoppieMessage, MessageType
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


def test_atis_unavailable_prints_once_per_airport_fallback(app_session):
    first = HoppieMessage(
        callsign="DLH9911",
        sender="acars",
        recipient="DLH9911",
        message_type=MessageType.INFOREQ,
        raw_payload="{acars info {THIS ATIS IS NOT\nAVAILABLE}}",
        normalized_body="VATATIS EDDF_D\nTHIS ATIS IS NOT\nAVAILABLE",
    )
    second = HoppieMessage(
        callsign="DLH9911",
        sender="acars",
        recipient="DLH9911",
        message_type=MessageType.INFOREQ,
        raw_payload="{acars info {THIS ATIS IS NOT\nAVAILABLE}}",
        normalized_body="VATATIS EDDF\nTHIS ATIS IS NOT\nAVAILABLE",
    )
    stats1 = app_session.ingestion.ingest([first], force_print=True)
    stats2 = app_session.ingestion.ingest([second], force_print=True)
    assert stats1["printed"] == 1
    assert stats2["stored"] == 1
    assert stats2["printed"] == 0
    assert app_session.db.conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"] == 2
    assert app_session.db.conn.execute("SELECT COUNT(*) AS c FROM print_jobs").fetchone()["c"] == 1


def test_atis_unavailable_never_force_reprints(app_session):
    msg = HoppieMessage(
        callsign="DLH9911",
        sender="acars",
        recipient="DLH9911",
        message_type=MessageType.INFOREQ,
        raw_payload="x",
        normalized_body="VATATIS EDDF\nTHIS ATIS IS NOT\nAVAILABLE",
    )
    assert app_session.ingestion.ingest([msg], force_print=True)["printed"] == 1
    # Same body again (plane retry) — store path is duplicate; must not reprint.
    stats = app_session.ingestion.ingest([msg], force_print=True)
    assert stats["duplicates"] == 1
    assert stats["printed"] == 0
    assert app_session.db.conn.execute("SELECT COUNT(*) AS c FROM print_jobs").fetchone()["c"] == 1


def test_atis_unavailable_different_airports_both_print(app_session):
    eddf = HoppieMessage(
        callsign="DLH9911",
        sender="acars",
        recipient="DLH9911",
        message_type=MessageType.INFOREQ,
        raw_payload="x",
        normalized_body="VATATIS EDDF\nTHIS ATIS IS NOT\nAVAILABLE",
    )
    egll = HoppieMessage(
        callsign="DLH9911",
        sender="acars",
        recipient="DLH9911",
        message_type=MessageType.INFOREQ,
        raw_payload="y",
        normalized_body="VATATIS EGLL\nTHIS ATIS IS NOT\nAVAILABLE",
    )
    assert app_session.ingestion.ingest([eddf])["printed"] == 1
    assert app_session.ingestion.ingest([egll])["printed"] == 1
