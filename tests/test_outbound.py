from __future__ import annotations

import httpx
import pytest

from acars_bridge.config import AppPaths
from acars_bridge.hoppie.client import HoppieClient
from acars_bridge.hoppie.errors import CallsignInUseError, SendNotAllowedError
from acars_bridge.hoppie.observer import ObserverTransport
from acars_bridge.hoppie.station import StationTransport
from acars_bridge.services.session import build_session


class _Router(httpx.BaseTransport):
    def __init__(self, routes: dict[str, str]):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        from urllib.parse import parse_qs

        parsed = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        key = parsed.get("type", "")
        body = self.routes.get(key, "ok")
        return httpx.Response(200, text=body)


def test_station_uses_poll_observer_uses_peek(fixture_text):
    router = _Router(
        {
            "poll": fixture_text("cpdlc_short.txt"),
            "peek": fixture_text("telex_simple.txt"),
        }
    )
    client = HoppieClient("https://example.test/connect.html", transport=router)
    station = StationTransport(client)
    observer = ObserverTransport(client)

    station_msgs = station.fetch("secret", "SWR14")
    observer_msgs = observer.fetch("secret", "SWR14")

    from urllib.parse import parse_qs

    sent_types = [parse_qs(r.content.decode())["type"][0] for r in router.requests]
    assert sent_types == ["poll", "peek"]
    assert station_msgs[0].message_type.value == "cpdlc"
    assert observer_msgs[0].message_type.value == "telex"


def test_observer_rejects_send():
    client = HoppieClient("https://example.test/connect.html", transport=_Router({}))
    with pytest.raises(SendNotAllowedError):
        ObserverTransport(client).send_telex("x", "SWR14", "ATC", "hi")


def test_callsign_in_use(fixture_text):
    router = _Router({"poll": fixture_text("callsign_in_use.txt")})
    client = HoppieClient("https://example.test/connect.html", transport=router)
    with pytest.raises(CallsignInUseError):
        StationTransport(client).fetch("secret", "SWR14")


def test_session_outbound_is_disabled(tmp_path, fixture_text):
    """Default Observer/tap mode never sends; plane owns the callsign."""
    router = _Router({"telex": "ok", "inforeq": fixture_text("inforeq_metar.txt")})
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True)
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret-logon-code")

    from acars_bridge.hoppie.requests import WeatherKind

    with pytest.raises(SendNotAllowedError):
        session.outbound.send_telex("SWROPS", "HELLO")
    with pytest.raises(SendNotAllowedError):
        session.outbound.request_weather(WeatherKind.METAR, "EGLL")
    assert not router.requests
    session.close()


def test_settings_mode_is_always_observer(tmp_path):
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    from acars_bridge.hoppie.types import ClientMode

    session.settings.set_mode(ClientMode.STATION)
    assert session.settings.mode() is ClientMode.OBSERVER
    assert session.transport() is session.observer
    session.close()
