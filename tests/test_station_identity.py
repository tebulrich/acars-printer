from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx

from acars_bridge.config import AppPaths
from acars_bridge.hoppie.client import HoppieClient
from acars_bridge.hoppie.requests import WeatherKind
from acars_bridge.hoppie.types import HoppieMessage, MessageType
from acars_bridge.services.session import build_session
from acars_bridge.services.station_identity import (
    StationIdentity,
    resolve_station_identity,
)
from acars_bridge.simbrief.models import SimBriefFlightPlan

FIXTURE = Path(__file__).parent / "fixtures" / "simbrief" / "sample_ofp.json"


class _Router(httpx.BaseTransport):
    def __init__(self, routes: dict[str, str] | None = None):
        self.routes = routes or {}
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        parsed = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        key = parsed.get("type", "")
        body = self.routes.get(key, "ok")
        return httpx.Response(200, text=body)


def _sample_plan() -> SimBriefFlightPlan:
    return SimBriefFlightPlan.from_json(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_network_callsign_wins_over_simbrief_and_inbox(tmp_path):
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    session.settings.set_callsign("SWR14")
    session.settings.set_station_callsign("OLD99")
    session.ensure_simbrief_watcher().state.plan = _sample_plan()  # DLH4MC
    session.messages.insert_inbound(
        HoppieMessage(
            callsign="BAW123",
            sender="SERVER",
            recipient="BAW123",
            message_type=MessageType.TELEX,
            raw_payload="ok",
            normalized_body="hi",
        ),
        fingerprint="test-baw123",
    )
    ident = resolve_station_identity(session)
    assert ident == StationIdentity(callsign="SWR14", source="network")
    session.close()


def test_simbrief_used_when_network_empty(tmp_path):
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    session.settings.set_callsign("")
    session.ensure_simbrief_watcher().state.plan = _sample_plan()
    ident = resolve_station_identity(session)
    assert ident.callsign == "DLH4MC"
    assert ident.source == "simbrief"
    assert session.settings.station_callsign() == "DLH4MC"
    session.close()


def test_inbox_used_when_no_network_or_simbrief(tmp_path):
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    session.settings.set_callsign("")
    session.messages.insert_inbound(
        HoppieMessage(
            callsign="EZY881",
            sender="SERVER",
            recipient="EZY881",
            message_type=MessageType.TELEX,
            raw_payload="ok",
            normalized_body="hi",
        ),
        fingerprint="test-ezy881",
    )
    ident = resolve_station_identity(session)
    assert ident.callsign == "EZY881"
    assert ident.source == "message"
    assert session.settings.station_callsign() == "EZY881"
    session.close()


def test_remembered_survives_cleared_inbox(tmp_path):
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    session.settings.set_callsign("")
    session.settings.set_station_callsign("AFR442")
    ident = resolve_station_identity(session)
    assert ident.callsign == "AFR442"
    assert ident.source == "remembered"
    session.close()


def test_empty_when_nothing_available(tmp_path):
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    session.settings.set_callsign("")
    ident = resolve_station_identity(session)
    assert ident.callsign is None
    assert ident.source is None
    session.close()


def test_outbound_uses_inbox_callsign_when_network_empty(tmp_path, fixture_text):
    router = _Router({"inforeq": fixture_text("inforeq_metar.txt")})
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(
        AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True
    )
    session.settings.set_callsign("")
    session.settings.set_hoppie_logon("secret-logon-code")
    session.settings.set_companion_station_enabled(True)
    session.messages.insert_inbound(
        HoppieMessage(
            callsign="SWR99",
            sender="SERVER",
            recipient="SWR99",
            message_type=MessageType.TELEX,
            raw_payload="ok",
            normalized_body="prior",
        ),
        fingerprint="test-swr99",
    )
    rows = session.outbound.request_weather(WeatherKind.METAR, "LSZH")
    assert rows
    body = parse_qs(router.requests[0].content.decode())
    assert body["from"] == ["SWR99"]
    session.close()
