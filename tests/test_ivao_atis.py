"""IVAO ATIS — every ATC station carries its own nested atis.lines."""

from __future__ import annotations

import httpx

from acars_bridge.hoppie.ivao_atis import (
    fetch_ivao_atis,
    parse_ivao_atis_rows,
    parse_ivao_whazzup,
)
from acars_bridge.hoppie.requests import AtisSide


def test_parse_nested_atis_on_each_station() -> None:
    """Main Whazzup: EDDB_TWR.atis.lines, not a dedicated _ATIS callsign."""
    rows = [
        {
            "callsign": "EDDB_A_GND",
            "atcSession": {"position": "GND"},
            "atis": {
                "revision": "B",
                "lines": [
                    "ts-1.eu-west-2.ivao.aero/EDDB_A_GND",
                    "Berlin Brandenburg Information BRAVO recorded at 1530z",
                    "ARR RWY 24L 24R DEP RWY 24L 24R",
                ],
            },
        },
        {
            "callsign": "EDDB_TWR",
            "atcSession": {"position": "TWR"},
            "atis": {
                "revision": "B",
                "lines": [
                    "ts-1.eu-west-2.ivao.aero/EDDB_TWR",
                    "Berlin Brandenburg Information BRAVO recorded at 1540z",
                    "ARR RWY 24L 24R DEP RWY 24L 24R TL FL60",
                ],
            },
        },
        {
            "callsign": "EDDB_APP",
            "atis": {
                "revision": "B",
                "lines": [
                    "ts-1.eu-west-2.ivao.aero/EDDB_APP",
                    "Berlin Approach Information BRAVO",
                ],
            },
        },
    ]
    hits = parse_ivao_atis_rows(rows, "EDDB")
    assert [h.callsign for h in hits] == ["EDDB_TWR", "EDDB_APP", "EDDB_A_GND"]
    assert hits[0].atis_code == "B"
    assert "1540z" in hits[0].body()
    assert "ivao.aero" not in hits[0].body()


def test_parse_full_whazzup_clients_atcs() -> None:
    payload = {
        "clients": {
            "atcs": [
                {
                    "callsign": "EDDB_TWR",
                    "atis": {
                        "revision": "C",
                        "lines": ["ts-1.ivao.aero/EDDB_TWR", "Berlin Information CHARLIE"],
                    },
                }
            ]
        }
    }
    hits = parse_ivao_whazzup(payload, "EDDB")
    assert len(hits) == 1
    assert hits[0].callsign == "EDDB_TWR"
    assert "CHARLIE" in hits[0].body()


def test_parse_ivao_official_atis_array() -> None:
    rows = [
        {
            "callsign": "EDDF_APP",
            "revision": "B",
            "lines": [
                "ts-1.eu-west-2.ivao.aero/EDDF_APP",
                "Frankfurt Information BRAVO recorded at 1534z",
                "CONFIRM ATIS INFO BRAVO on initial contact",
            ],
        },
        {
            "callsign": "EDDF_TWR",
            "revision": "B",
            "lines": [
                "ts-1.eu-west-2.ivao.aero/EDDF_TWR",
                "Frankfurt Information BRAVO recorded at 1540z",
                "ARR RWY 25L DEP RWY 18",
            ],
        },
        {
            "callsign": "LFEE_CTR",
            "revision": "A",
            "lines": ["ts-1.eu-west-2.ivao.aero/LFEE_CTR", "CPDLC ID LFEE"],
        },
    ]
    hits = parse_ivao_atis_rows(rows, "EDDF")
    assert [h.callsign for h in hits] == ["EDDF_TWR", "EDDF_APP"]
    assert "ivao.aero" not in hits[0].body()
    assert "Frankfurt Information BRAVO" in hits[0].body()


def test_fetch_ivao_prefers_twr_combined() -> None:
    payload = [
        {
            "callsign": "EDDS_GND",
            "revision": "H",
            "lines": ["ts-1.ivao.aero/EDDS_GND", "Stuttgart Information HOTEL"],
        },
        {
            "callsign": "EDDS_TWR",
            "revision": "H",
            "lines": ["ts-1.ivao.aero/EDDS_TWR", "Stuttgart Information HOTEL TWR"],
        },
    ]

    class _Transport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

    with httpx.Client(transport=_Transport()) as client:
        hit = fetch_ivao_atis("EDDS", side=AtisSide.DEP, client=client)
    assert hit is not None
    assert hit.callsign == "EDDS_TWR"
    assert "HOTEL TWR" in hit.body()


def test_fetch_reads_nested_whazzup_atcs() -> None:
    payload = {
        "clients": {
            "atcs": [
                {
                    "callsign": "EDDB_TWR",
                    "atis": {
                        "revision": "B",
                        "lines": [
                            "ts-1.eu-west-2.ivao.aero/EDDB_TWR",
                            "Berlin Brandenburg Information BRAVO",
                        ],
                    },
                }
            ]
        }
    }

    class _Transport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

    with httpx.Client(transport=_Transport()) as client:
        hit = fetch_ivao_atis("EDDB", client=client)
    assert hit is not None
    assert hit.callsign == "EDDB_TWR"
    assert "BRAVO" in hit.body()
