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
    """Default Observer/tap mode never sends on Hoppie; plane owns the callsign."""
    router = _Router({"telex": "ok", "inforeq": fixture_text("inforeq_metar.txt")})
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True)
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret-logon-code")

    with pytest.raises(SendNotAllowedError) as exc:
        session.outbound.send_telex("SWROPS", "HELLO")
    assert "fenix" not in str(exc.value).lower()
    assert len(str(exc.value)) < 80
    assert not router.requests
    session.close()


def test_atis_uses_vatsim_feed_without_hoppie_session(tmp_path, monkeypatch):
    from acars_bridge.hoppie.requests import AtisSource
    from acars_bridge.hoppie.vatsim_atis import VatsimAtis

    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    session.settings.set_companion_station_enabled(False)
    monkeypatch.setattr(
        "acars_bridge.services.outbound.list_vatsim_atis",
        lambda icao, client=None: [
            VatsimAtis(callsign="EDDF_D_ATIS", lines=["EDDF DEP ATIS G"], atis_code="G")
        ],
    )
    monkeypatch.setattr(
        "acars_bridge.services.outbound.fetch_vatsim_atis",
        lambda icao, side=None, client=None: VatsimAtis(
            callsign="EDDF_D_ATIS", lines=["EDDF DEP ATIS G"], atis_code="G"
        ),
    )
    rows = session.outbound.request_atis("EDDF", source=AtisSource.VATSIM, side="dep")
    assert rows
    bodies = " ".join(r.normalized_body for r in rows)
    assert "EDDF DEP ATIS G" in bodies
    session.close()


def test_weather_uses_awc_without_hoppie_session(tmp_path, monkeypatch):
    from acars_bridge.hoppie.requests import WeatherKind

    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    session.settings.set_companion_station_enabled(False)
    monkeypatch.setattr(
        "acars_bridge.services.outbound.fetch_metar_raw",
        lambda icao, client=None: "EDDF 161320Z 23008KT CAVOK",
    )
    rows = session.outbound.request_weather(WeatherKind.METAR, "EDDF")
    assert rows
    bodies = " ".join(r.normalized_body for r in rows)
    assert "EDDF 161320Z" in bodies
    session.close()


def test_atis_missing_vatsim_is_a_short_error(tmp_path, monkeypatch):
    from acars_bridge.hoppie.errors import HoppieError
    from acars_bridge.hoppie.requests import AtisSource
    from acars_bridge.hoppie.vatsim_atis import VatsimAtis

    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    monkeypatch.setattr(
        "acars_bridge.services.outbound.list_vatsim_atis",
        lambda icao, client=None: [],
    )
    monkeypatch.setattr(
        "acars_bridge.services.outbound.fetch_vatsim_atis",
        lambda icao, side=None, client=None: None,
    )
    ivao_calls: list[str] = []

    def _ivao(icao: str, side=None, client=None) -> VatsimAtis:
        ivao_calls.append(icao)
        return VatsimAtis(callsign="EDDF_TWR", lines=["INFO MIKE"], atis_code="M")

    monkeypatch.setattr("acars_bridge.services.outbound.fetch_ivao_atis", _ivao)
    with pytest.raises(HoppieError) as exc:
        session.outbound.request_atis("EDDF", source=AtisSource.VATSIM)
    assert str(exc.value) == "No VATSIM ATIS for EDDF."
    assert ivao_calls == []
    session.close()


def test_atis_ivao_does_not_use_vatsim(tmp_path, monkeypatch):
    from acars_bridge.hoppie.requests import AtisSource
    from acars_bridge.hoppie.vatsim_atis import VatsimAtis

    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    monkeypatch.setattr(
        "acars_bridge.services.outbound.fetch_vatsim_atis",
        lambda icao, side=None, client=None: VatsimAtis(
            callsign="EDDF_ATIS", lines=["INFO TANGO"], atis_code="T"
        ),
    )
    monkeypatch.setattr(
        "acars_bridge.services.outbound.fetch_ivao_atis",
        lambda icao, side=None, client=None: VatsimAtis(
            callsign="EDDF_TWR", lines=["INFO MIKE"], atis_code="M"
        ),
    )
    rows = session.outbound.request_atis("EDDF", source=AtisSource.IVAO)
    bodies = " ".join(r.normalized_body for r in rows)
    assert "INFO MIKE" in bodies
    assert "INFO TANGO" not in bodies
    assert session.settings.atis_source() is AtisSource.IVAO
    session.close()


def test_atis_auto_picks_dep_on_ground_without_combined(tmp_path, monkeypatch):
    from acars_bridge.hoppie.requests import AtisSource
    from acars_bridge.hoppie.vatsim_atis import VatsimAtis
    from acars_bridge.simconnect.monitor import SimSnapshot

    class _Snap:
        def snapshot(self) -> SimSnapshot:
            return SimSnapshot(
                connected=True,
                source="simconnect",
                in_session=True,
                on_ground=True,
            )

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    seen: list[object] = []

    def _fetch(icao: str, side=None, client=None) -> VatsimAtis:
        seen.append(side)
        return VatsimAtis(callsign="KMIA_D_ATIS", lines=["DEP INFO D"], atis_code="D")

    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    session.simconnect = _Snap()  # type: ignore[assignment]
    monkeypatch.setattr(
        "acars_bridge.services.outbound.list_vatsim_atis",
        lambda icao, client=None: [
            VatsimAtis(callsign="KMIA_D_ATIS", lines=["DEP INFO D"], atis_code="D"),
            VatsimAtis(callsign="KMIA_A_ATIS", lines=["ARR INFO A"], atis_code="A"),
        ],
    )
    monkeypatch.setattr("acars_bridge.services.outbound.fetch_vatsim_atis", _fetch)
    rows = session.outbound.request_atis("KMIA", source=AtisSource.VATSIM)
    assert rows
    from acars_bridge.hoppie.requests import AtisSide

    assert seen == [AtisSide.DEP]
    session.close()


def test_settings_mode_is_always_observer(tmp_path):
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    from acars_bridge.hoppie.types import ClientMode

    session.settings.set_mode(ClientMode.STATION)
    assert session.settings.mode() is ClientMode.OBSERVER
    assert session.transport() is session.observer
    session.close()
