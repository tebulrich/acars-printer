from __future__ import annotations

import pytest

from acars_bridge.hoppie.requests import (
    AtisSide,
    AtisSource,
    WeatherKind,
    build_atis_packet,
    build_pdc_telex,
    build_position_packet,
    build_weather_packet,
)


def test_build_weather_and_atis_packets():
    assert build_weather_packet(WeatherKind.METAR, "egll") == "metar EGLL"
    assert build_weather_packet("taf", "EDDM") == "taf EDDM"
    assert (
        build_atis_packet("EGLL", source=AtisSource.VATSIM, side=AtisSide.DEP)
        == "vatatis EGLL_D_ATIS"
    )
    assert (
        build_atis_packet("EGLL", source=AtisSource.VATSIM, side=AtisSide.ARR)
        == "vatatis EGLL_A_ATIS"
    )
    assert build_atis_packet("EGLL", source=AtisSource.VATSIM, side=None) == "vatatis EGLL"
    assert build_atis_packet("LFPG", source=AtisSource.IVAO, side=AtisSide.DEP) == "ivaoatis LFPG"


def test_build_pdc_and_position():
    body = build_pdc_telex(
        callsign="DLH4KM",
        aircraft_type="A320",
        destination="eddm",
        departure="eddf",
        stand="a36",
        atis_letter="d",
    )
    assert "REQUEST PREDEP CLEARANCE" in body
    assert "DLH4KM A320 TO EDDM" in body
    assert "AT EDDF STAND A36" in body
    assert "ATIS D" in body

    pos = build_position_packet(
        latitude="N5030.0",
        longitude="E00845.0",
        altitude="FL360",
        time_utc="1435Z",
        next_waypoint="SIDNE",
        eta="1505Z",
    )
    assert "LAT N5030.0" in pos
    assert "NEXT SIDNE" in pos


def test_builders_validate_inputs():
    with pytest.raises(ValueError):
        build_weather_packet(WeatherKind.METAR, "XX")
    with pytest.raises(ValueError):
        build_pdc_telex(
            callsign="SWR14",
            aircraft_type="A320",
            destination="LSGG",
            departure="LSZH",
            stand="1",
            atis_letter="DD",
        )
