from __future__ import annotations

from acars_bridge.tap.extract import messages_from_hoppie_exchange, parse_form_body


def test_parse_form_body():
    form = parse_form_body(b"logon=x&from=BSC612&to=SERVER&type=inforeq&packet=metar+EGLL")
    assert form["from"] == "BSC612"
    assert form["type"] == "inforeq"
    assert form["packet"] == "metar EGLL"


def test_inforeq_exchange_force_prints(fixture_text):
    form = {
        "from": "BSC612",
        "type": "inforeq",
        "packet": "metar EGLL",
    }
    messages, force = messages_from_hoppie_exchange(
        request_form=form,
        response_text=fixture_text("inforeq_metar.txt"),
        callsign_filter="BSC612",
    )
    assert force is True
    assert messages
    assert messages[0].normalized_body.startswith("METAR EGLL\n")
    assert "EGLL" in messages[0].normalized_body


def test_inforeq_keeps_vatatis_station_on_unavailable():
    form = {
        "from": "DLH9911",
        "type": "inforeq",
        "packet": "vatatis EDDF",
    }
    response = "ok {acars info {THIS ATIS IS NOT\nAVAILABLE}}"
    messages, force = messages_from_hoppie_exchange(
        request_form=form,
        response_text=response,
        callsign_filter="DLH9911",
    )
    assert force is True
    assert len(messages) == 1
    assert messages[0].normalized_body == "VATATIS EDDF\nTHIS ATIS IS NOT\nAVAILABLE"


def test_poll_exchange_normal(fixture_text):
    form = {"from": "BSC612", "type": "poll", "packet": ""}
    messages, force = messages_from_hoppie_exchange(
        request_form=form,
        response_text=fixture_text("cpdlc_short.txt"),
        callsign_filter="BSC612",
    )
    assert force is False
    assert messages
    assert messages[0].message_type.value == "cpdlc"


def test_callsign_filter_skips_other_flights(fixture_text):
    form = {"from": "AAA123", "type": "inforeq", "packet": "metar EGLL"}
    messages, force = messages_from_hoppie_exchange(
        request_form=form,
        response_text=fixture_text("inforeq_metar.txt"),
        callsign_filter="BSC612",
    )
    assert messages == []
    assert force is False


def test_ping_ignored():
    messages, force = messages_from_hoppie_exchange(
        request_form={"from": "BSC612", "type": "ping"},
        response_text="ok",
    )
    assert messages == []
    assert force is False


def test_sniffed_info_body_without_form_type(fixture_text):
    messages, force = messages_from_hoppie_exchange(
        request_form={},
        response_text=fixture_text("inforeq_metar.txt"),
        callsign_filter="BSC612",
    )
    assert force is True
    assert messages
    assert messages[0].callsign == "BSC612"
