from __future__ import annotations

import pytest

from acars_bridge.hoppie.errors import CallsignInUseError, HoppieError
from acars_bridge.hoppie.parser import parse_response
from acars_bridge.hoppie.types import MessageType


def test_empty_ok(fixture_text):
    assert parse_response(fixture_text("empty_ok.txt"), "SWR14") == []


def test_cpdlc_short(fixture_text):
    messages = parse_response(fixture_text("cpdlc_short.txt"), "SWR14")
    assert len(messages) == 1
    msg = messages[0]
    assert msg.message_type is MessageType.CPDLC
    assert msg.sender == "LSAS_CTR"
    assert msg.callsign == "SWR14"
    assert msg.min == 15
    assert msg.ra == "WU"
    assert "CLIMB TO AND MAINTAIN FL360" in msg.normalized_body


def test_long_route_preserves_tokens(fixture_text):
    messages = parse_response(fixture_text("cpdlc_long_route.txt"), "SWR14")
    body = messages[0].normalized_body
    assert "N850" in body
    assert "TOLEN" in body
    assert "GERSA" in body


def test_telex_and_multi(fixture_text):
    telex = parse_response(fixture_text("telex_simple.txt"), "SWR14")
    multi = parse_response(fixture_text("multi_messages.txt"), "SWR14")
    assert telex[0].message_type is MessageType.TELEX
    assert len(multi) == 2
    assert multi[0].message_type is MessageType.CPDLC
    assert multi[1].message_type is MessageType.TELEX


def test_malformed_and_errors(fixture_text):
    with pytest.raises(HoppieError):
        parse_response(fixture_text("malformed.txt"), "SWR14")
    with pytest.raises(HoppieError, match="logon code not accepted"):
        parse_response(fixture_text("error_logon.txt"), "SWR14")
    with pytest.raises(CallsignInUseError):
        parse_response(fixture_text("callsign_in_use.txt"), "SWR14")
