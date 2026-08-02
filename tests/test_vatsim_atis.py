from __future__ import annotations

import httpx

from acars_bridge.hoppie.requests import AtisSide
from acars_bridge.hoppie.vatsim_atis import (
    fetch_vatsim_atis,
    hoppie_vatatis_packets,
)


class _DataTransport(httpx.BaseTransport):
    def __init__(self, payload: dict):
        self.payload = payload

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=self.payload)


def test_hoppie_packets_use_plain_icao_for_combined_atis():
    # EDDN-style: only combined station online → never invent _D_ATIS
    packets = hoppie_vatatis_packets(
        "EDDN",
        side=AtisSide.DEP,
        online_callsigns={"EDDN_ATIS"},
    )
    assert packets[0] == "vatatis EDDN"
    assert "vatatis EDDN_D_ATIS" not in packets


def test_hoppie_packets_use_split_when_online():
    packets = hoppie_vatatis_packets(
        "KMIA",
        side=AtisSide.DEP,
        online_callsigns={"KMIA_D_ATIS", "KMIA_A_ATIS"},
    )
    assert packets[0] == "vatatis KMIA_D_ATIS"
    assert "vatatis KMIA" in packets


def test_fetch_vatsim_atis_prefers_online_combined():
    payload = {
        "atis": [
            {
                "callsign": "EDDN_ATIS",
                "atis_code": "J",
                "text_atis": ["NUERNBERG INFORMATION J", "RWY 10"],
            }
        ]
    }
    with httpx.Client(transport=_DataTransport(payload)) as client:
        hit = fetch_vatsim_atis("EDDN", side=AtisSide.DEP, client=client)
        assert hit is not None
        assert hit.callsign == "EDDN_ATIS"
        assert "NUERNBERG INFORMATION J" in hit.body()


def test_fetch_vatsim_atis_prefers_split_when_present():
    payload = {
        "atis": [
            {
                "callsign": "EDDS_ATIS",
                "atis_code": "K",
                "text_atis": ["ATIS EDDS K"],
            },
            {
                "callsign": "EDDS_D_ATIS",
                "atis_code": "D",
                "text_atis": ["DEP INFO D"],
            },
        ]
    }
    with httpx.Client(transport=_DataTransport(payload)) as client:
        dep = fetch_vatsim_atis("EDDS", side=AtisSide.DEP, client=client)
        assert dep is not None
        assert dep.callsign == "EDDS_D_ATIS"
