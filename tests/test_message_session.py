from __future__ import annotations

from acars_bridge.hoppie.parser import parse_response


def test_clear_all_wipes_message_history(app_session, fixture_text):
    messages = parse_response(fixture_text("cpdlc_short.txt"), "SWR14")
    stored = app_session.ingestion.ingest(messages, auto_print=False)
    assert stored["stored"] >= 1
    assert app_session.messages.list_recent(10)

    app_session.messages.clear_all()
    assert app_session.messages.list_recent(10) == []
