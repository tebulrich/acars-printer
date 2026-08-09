from __future__ import annotations

from acars_bridge.hoppie.parser import parse_response


def test_set_printable_types_roundtrip(app_session) -> None:
    settings = app_session.settings
    settings.set_printable_types(["telex", "CPDLC"])
    assert settings.printable_types() == {"telex", "cpdlc"}
    settings.set_printable_types([])
    assert settings.printable_types() == set()


def test_set_printable_types_ignores_unknown(app_session) -> None:
    settings = app_session.settings
    settings.set_printable_types(["cpdlc", "bogus", "inforeq"])
    assert settings.printable_types() == {"cpdlc", "inforeq"}


def test_empty_printable_types_stores_not_prints(app_session, fixture_text) -> None:
    app_session.settings.set_printable_types([])
    messages = parse_response(fixture_text("cpdlc_short.txt"), "SWR14")
    stats = app_session.ingestion.ingest(messages)
    assert stats["stored"] == 1
    assert stats["printed"] == 0
