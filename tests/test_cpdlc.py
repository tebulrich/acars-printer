from __future__ import annotations

import pytest

from acars_bridge.hoppie.cpdlc import CpdlcPacket


def test_parse_uplink():
    packet = CpdlcPacket.parse("/data2/15//WU/CLIMB TO AND MAINTAIN@FL360")
    assert packet.min == 15
    assert packet.mrn is None
    assert packet.ra == "WU"
    assert packet.requires_reply()
    assert packet.display_text == "CLIMB TO AND MAINTAIN\nFL360"


def test_build_and_encode_reply():
    reply = CpdlcPacket.build_reply(our_min=7, uplink_min=15, reply="wilco")
    assert reply.encode() == "/data2/7/15/N/WILCO"


def test_rejects_unknown_reply():
    with pytest.raises(ValueError):
        CpdlcPacket.build_reply(our_min=1, uplink_min=2, reply="MAYBE")
