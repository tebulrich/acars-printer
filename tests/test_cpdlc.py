from __future__ import annotations

import pytest

from acars_bridge.hoppie.cpdlc import CpdlcPacket, reply_choices


def test_parse_uplink():
    packet = CpdlcPacket.parse("/data2/15//WU/CLIMB TO AND MAINTAIN@FL360")
    assert packet.min == 15
    assert packet.mrn is None
    assert packet.ra == "WU"
    assert packet.requires_reply()
    # @ is a CDU wrap mark, not a thermal line break.
    assert packet.display_text == "CLIMB TO AND MAINTAIN FL360"


def test_pdc_at_wrappers_become_spaces():
    """VATSIM PDC wraps fill-ins as @EDDM@ — must not print one word per row."""
    packet = CpdlcPacket.parse(
        "/data2/32//WU/CLD 1552 260811 EDDF PDC 010 DLH4MCCLRD TO "
        "@EDDM@ OFF @18@ VIA @CINDY8S@ SQUAWK @1000@ NEXT FREQ "
        "@121.855@ ATIS @F@ REPORT TOBT AT VATS.IM|VDGS REPORT READY ON "
        "@121.855@ ACC TSAT"
    )
    text = packet.display_text
    assert "\nEDDM\n" not in text
    assert "\n18\n" not in text
    assert "TO EDDM OFF 18 VIA CINDY8S SQUAWK 1000" in text
    assert "NEXT FREQ 121.855 ATIS F" in text


def test_double_at_is_paragraph_break():
    packet = CpdlcPacket.parse("/data2/1//N/STANDBY@@CONTACT TWR")
    assert packet.display_text == "STANDBY\nCONTACT TWR"


def test_build_and_encode_reply():
    reply = CpdlcPacket.build_reply(our_min=7, uplink_min=15, reply="wilco")
    assert reply.encode() == "/data2/7/15/N/WILCO"


def test_rejects_unknown_reply():
    with pytest.raises(ValueError):
        CpdlcPacket.build_reply(our_min=1, uplink_min=2, reply="MAYBE")


def test_reply_choices_follow_ra():
    assert reply_choices("WU") == ["WILCO", "UNABLE", "STANDBY"]
    assert reply_choices("AN") == ["AFFIRM", "NEGATIVE", "STANDBY"]
    assert reply_choices("R") == ["ROGER", "STANDBY"]
    assert reply_choices("N") == []
    assert reply_choices(None) == []


def test_build_affirm_reply():
    reply = CpdlcPacket.build_reply(our_min=3, uplink_min=9, reply="affirm")
    assert reply.encode() == "/data2/3/9/N/AFFIRM"
