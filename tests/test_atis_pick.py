"""Auto ATIS side: combined first, else dep on ground / arrival in air."""

from __future__ import annotations

from acars_bridge.hoppie.atis_pick import (
    atis_side_from_snapshot,
    is_combined_callsign,
    pick_network_atis,
)
from acars_bridge.hoppie.requests import AtisSide
from acars_bridge.hoppie.vatsim_atis import VatsimAtis
from acars_bridge.simconnect.monitor import SimSnapshot


def _atis(callsign: str, text: str) -> VatsimAtis:
    return VatsimAtis(callsign=callsign, lines=[text], atis_code="A")


def test_combined_callsign_is_icao_atis_only() -> None:
    assert is_combined_callsign("EDDF_ATIS", "EDDF") is True
    assert is_combined_callsign("EDDF_D_ATIS", "EDDF") is False
    assert is_combined_callsign("EDDF_A_ATIS", "EDDF") is False
    assert is_combined_callsign("EDDF_TWR", "EDDF") is False


def test_side_from_snapshot_ground_air_and_menu() -> None:
    ground = SimSnapshot(
        connected=True, source="simconnect", in_session=True, on_ground=True
    )
    air = SimSnapshot(
        connected=True, source="simconnect", in_session=True, on_ground=False
    )
    menu = SimSnapshot(
        connected=True, source="simconnect", in_session=False, on_ground=True
    )
    assert atis_side_from_snapshot(ground) is AtisSide.DEP
    assert atis_side_from_snapshot(air) is AtisSide.ARR
    assert atis_side_from_snapshot(menu) is None
    assert atis_side_from_snapshot(None) is None


def test_pick_always_prefers_combined() -> None:
    hit = pick_network_atis(
        [
            _atis("EDDS_ATIS", "COMBINED K"),
            _atis("EDDS_D_ATIS", "DEP D"),
            _atis("EDDS_A_ATIS", "ARR A"),
        ],
        icao="EDDS",
        side=AtisSide.DEP,
    )
    assert hit is not None
    assert hit.callsign == "EDDS_ATIS"


def test_pick_dep_when_no_combined() -> None:
    hit = pick_network_atis(
        [_atis("KMIA_D_ATIS", "DEP"), _atis("KMIA_A_ATIS", "ARR")],
        icao="KMIA",
        side=AtisSide.DEP,
    )
    assert hit is not None
    assert hit.callsign == "KMIA_D_ATIS"


def test_pick_arr_when_no_combined() -> None:
    hit = pick_network_atis(
        [_atis("KMIA_D_ATIS", "DEP"), _atis("KMIA_A_ATIS", "ARR")],
        icao="KMIA",
        side=AtisSide.ARR,
    )
    assert hit is not None
    assert hit.callsign == "KMIA_A_ATIS"


def test_pick_fallback_combined_when_side_missing() -> None:
    hit = pick_network_atis(
        [_atis("KMIA_D_ATIS", "DEP"), _atis("KMIA_A_ATIS", "ARR")],
        icao="KMIA",
        side=None,
    )
    assert hit is not None
    assert hit.callsign in {"KMIA_D_ATIS", "KMIA_A_ATIS"}
