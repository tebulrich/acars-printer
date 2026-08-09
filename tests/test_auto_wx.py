from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from acars_bridge.simbrief.models import SimBriefFlightPlan
from acars_bridge.simconnect.monitor import SimSnapshot
from acars_bridge.weather.auto_wx import AutoWxService, should_trigger_dest_wx
from acars_bridge.weather.awc import fetch_airport_coords, fetch_metar_raw, fetch_taf_raw
from acars_bridge.weather.distance import great_circle_nm


@pytest.fixture
def sample_plan() -> SimBriefFlightPlan:
    root = json.loads(
        (Path(__file__).parent / "fixtures" / "simbrief" / "sample_ofp.json").read_text(
            encoding="utf-8"
        )
    )
    return SimBriefFlightPlan.from_json(root)


def test_great_circle_eddf_eddm_about_160_nm() -> None:
    # Frankfurt ≈ 50.03N 8.57E, Munich ≈ 48.35N 11.79E
    nm = great_circle_nm(50.03, 8.57, 48.35, 11.79)
    assert 140 < nm < 190


def test_should_trigger_airborne_within_ring_including_short_hop() -> None:
    # Classic approach — airborne, away from origin, inside dest ring.
    assert (
        should_trigger_dest_wx(
            distance_to_dest_nm=120,
            distance_to_origin_nm=200,
            threshold_nm=150,
            on_ground=False,
        )
        is True
    )
    # Near origin on ground (short hop / preflight) — suppress.
    assert (
        should_trigger_dest_wx(
            distance_to_dest_nm=140,
            distance_to_origin_nm=10,
            threshold_nm=150,
            on_ground=True,
        )
        is False
    )
    # Short hop already inside ring — once airborne, allow (do not require
    # "far from origin").
    assert (
        should_trigger_dest_wx(
            distance_to_dest_nm=140,
            distance_to_origin_nm=10,
            threshold_nm=150,
            on_ground=False,
        )
        is True
    )
    # Still too far from destination.
    assert (
        should_trigger_dest_wx(
            distance_to_dest_nm=200,
            distance_to_origin_nm=50,
            threshold_nm=150,
            on_ground=False,
        )
        is False
    )


def test_awc_metar_and_airport_parse() -> None:
    class _T(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/metar"):
                return httpx.Response(
                    200,
                    json=[
                        {
                            "icaoId": "EDDM",
                            "rawOb": "EDDM 091020Z 27008KT 9999 SCT030 12/05 Q1018",
                            "lat": 48.35,
                            "lon": 11.79,
                        }
                    ],
                )
            if path.endswith("/taf"):
                return httpx.Response(
                    200,
                    json=[
                        {
                            "icaoId": "EDDM",
                            "rawTAF": "TAF EDDM 090900Z 0910/1016 27010KT CAVOK",
                        }
                    ],
                )
            if path.endswith("/airport"):
                return httpx.Response(
                    200,
                    json=[{"icaoId": "EDDM", "lat": 48.3538, "lon": 11.7861}],
                )
            return httpx.Response(404)

    with httpx.Client(transport=_T()) as client:
        metar = fetch_metar_raw("EDDM", client=client)
        assert metar is not None
        assert metar.startswith("EDDM")
        taf = fetch_taf_raw("EDDM", client=client)
        assert taf is not None and "TAF EDDM" in taf
        coords = fetch_airport_coords("EDDM", client=client)
        assert coords is not None
        assert abs(coords[0] - 48.3538) < 0.01


def _awc_transport_eddf_eddm() -> httpx.BaseTransport:
    class _T(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            path = request.url.path
            ids = (request.url.params.get("ids") or "").upper()
            if path.endswith("/metar"):
                if ids == "EDDM":
                    return httpx.Response(
                        200,
                        json=[
                            {
                                "icaoId": "EDDM",
                                "rawOb": "EDDM 091020Z 27008KT CAVOK",
                                "lat": 48.35,
                                "lon": 11.79,
                            }
                        ],
                    )
                return httpx.Response(200, json=[])
            if path.endswith("/airport"):
                if ids == "EDDM":
                    return httpx.Response(
                        200,
                        json=[{"icaoId": "EDDM", "lat": 48.35, "lon": 11.79}],
                    )
                if ids == "EDDF":
                    return httpx.Response(
                        200,
                        json=[{"icaoId": "EDDF", "lat": 50.03, "lon": 8.57}],
                    )
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[])

    return _T()


def test_auto_wx_prints_once_per_ofp(app_session, sample_plan: SimBriefFlightPlan) -> None:
    app_session.settings.set_wx_auto_enabled(True)
    app_session.settings.set_wx_auto_nm(150)
    app_session.settings.set_wx_auto_kinds(["metar"])
    app_session.sterile.update_from_snapshot(
        SimSnapshot(
            connected=True,
            on_ground=False,
            ground_velocity_kt=420,
            alt_agl_ft=35000,
            latitude=48.9,
            longitude=10.5,
        )
    )

    # ~120 nm from Munich while far from Frankfurt
    snap = SimSnapshot(
        connected=True,
        on_ground=False,
        ground_velocity_kt=420,
        alt_agl_ft=35000,
        latitude=48.9,
        longitude=10.5,
    )
    svc = AutoWxService(
        settings=app_session.settings,
        print_manager=app_session.print_manager,
        sterile=app_session.sterile,
        http_client=httpx.Client(transport=_awc_transport_eddf_eddm()),
    )
    printed = svc.consider(snap, sample_plan)
    assert printed >= 1
    printer = app_session.print_manager._printer
    assert len(printer.printed) >= 1
    assert "EDDM" in printer.printed[0][1]
    # Second consider — no duplicate
    n = len(printer.printed)
    assert svc.consider(snap, sample_plan) == 0
    assert len(printer.printed) == n


def test_auto_wx_short_hop_waits_for_airborne_then_prints_once(
    app_session, sample_plan: SimBriefFlightPlan
) -> None:
    """Dest already inside NM ring: suppress on ground near origin; print once airborne."""
    app_session.settings.set_wx_auto_enabled(True)
    # EDDF–EDDM ≈ 160 NM — ring large enough that departure starts inside.
    app_session.settings.set_wx_auto_nm(200)
    app_session.settings.set_wx_auto_kinds(["metar"])

    # Near EDDF (~origin), already within dest ring — on ground.
    ground = SimSnapshot(
        connected=True,
        on_ground=True,
        ground_velocity_kt=0,
        alt_agl_ft=0,
        latitude=50.03,
        longitude=8.57,
    )
    app_session.sterile.update_from_snapshot(ground)
    svc = AutoWxService(
        settings=app_session.settings,
        print_manager=app_session.print_manager,
        sterile=app_session.sterile,
        http_client=httpx.Client(transport=_awc_transport_eddf_eddm()),
    )
    assert svc.consider(ground, sample_plan) == 0
    assert app_session.print_manager._printer.printed == []

    # Airborne + sterile clear (above AGL) while still "near origin" / in ring.
    air = SimSnapshot(
        connected=True,
        on_ground=False,
        ground_velocity_kt=220,
        alt_agl_ft=5000,
        latitude=50.0,
        longitude=8.7,
    )
    app_session.sterile.update_from_snapshot(air)
    assert not app_session.sterile.is_blocking
    assert svc.consider(air, sample_plan) >= 1
    printer = app_session.print_manager._printer
    assert len(printer.printed) >= 1
    assert "EDDM" in printer.printed[0][1]
    n = len(printer.printed)
    assert svc.consider(air, sample_plan) == 0
    assert len(printer.printed) == n


def test_wx_settings_roundtrip(app_session) -> None:
    s = app_session.settings
    assert s.wx_auto_enabled() is False
    assert s.wx_auto_nm() == 150
    s.set_wx_auto_enabled(True)
    s.set_wx_auto_nm(100)
    s.set_wx_auto_kinds(["atis", "metar"])
    assert s.wx_auto_enabled() is True
    assert s.wx_auto_nm() == 100
    assert s.wx_auto_kinds() == {"atis", "metar"}
