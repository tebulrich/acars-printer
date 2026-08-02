from __future__ import annotations

import httpx
import pytest

from acars_bridge.config import AppPaths
from acars_bridge.hoppie.client import HoppieClient
from acars_bridge.hoppie.errors import CallsignInUseError, SendNotAllowedError
from acars_bridge.hoppie.observer import ObserverTransport
from acars_bridge.hoppie.parser import parse_response
from acars_bridge.hoppie.station import StationTransport
from acars_bridge.hoppie.types import ClientMode
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


def test_send_telex_and_cpdlc_reply(tmp_path, fixture_text):
    router = _Router(
        {
            "telex": "ok",
            "cpdlc": "ok",
        }
    )
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True)
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret-logon-code")
    session.settings.set_mode(ClientMode.STATION)

    # Seed inbound CPDLC
    inbound = parse_response(fixture_text("cpdlc_short.txt"), "SWR14")
    session.ingestion.ingest(inbound, auto_print=False)
    msg_id = session.messages.list_recent(1)[0].id

    out_telex = session.outbound.send_telex("SWROPS", "HELLO OPS")
    assert out_telex.direction == "out"
    assert out_telex.send_status == "sent"

    out_reply = session.outbound.reply_cpdlc(msg_id, "WILCO")
    assert out_reply.normalized_body == "WILCO"
    assert out_reply.mrn == 15

    from urllib.parse import parse_qs

    types = [parse_qs(r.content.decode())["type"][0] for r in router.requests]
    assert "telex" in types
    assert "cpdlc" in types
    assert "poll" not in types  # sends only

    session.settings.set_mode(ClientMode.OBSERVER)
    with pytest.raises(SendNotAllowedError):
        session.outbound.send_telex("SWROPS", "NOPE")

    session.close()


def test_request_weather_ingests_inline_inforeq(tmp_path, fixture_text):
    router = _Router({"inforeq": fixture_text("inforeq_metar.txt")})
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True)
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret-logon-code")
    session.settings.set_mode(ClientMode.STATION)

    from acars_bridge.hoppie.requests import WeatherKind

    rows = session.outbound.request_weather(WeatherKind.METAR, "EGLL")
    from urllib.parse import parse_qs

    assert parse_qs(router.requests[0].content.decode())["type"][0] == "inforeq"
    assert parse_qs(router.requests[0].content.decode())["packet"][0] == "metar EGLL"
    inbound = [r for r in rows if r.direction == "in"]
    assert inbound
    assert "EGLL" in inbound[0].normalized_body
    assert inbound[0].message_type == "inforeq"
    session.close()


def test_request_pdc_and_position(tmp_path):
    router = _Router({"telex": "ok", "position": "ok"})
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True)
    session.settings.set_callsign("DLH4KM")
    session.settings.set_hoppie_logon("secret-logon-code")
    session.settings.set_mode(ClientMode.STATION)

    pdc = session.outbound.request_pdc(
        station="EDDF",
        departure="EDDF",
        destination="EDDM",
        aircraft_type="A320",
        stand="A36",
        atis_letter="D",
    )
    assert "REQUEST PREDEP CLEARANCE" in pdc.normalized_body

    pos = session.outbound.send_position(
        to="EDUU",
        latitude="N5030.0",
        longitude="E00845.0",
        altitude="FL360",
        time_utc="1435Z",
    )
    assert pos.message_type == "position"
    from urllib.parse import parse_qs

    types = [parse_qs(r.content.decode())["type"][0] for r in router.requests]
    assert types == ["telex", "position"]
    session.close()
