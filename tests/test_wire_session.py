"""Wire-session vault + phone outbound without companion station mode."""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

from acars_bridge.config import AppPaths
from acars_bridge.hoppie.client import HoppieClient
from acars_bridge.hoppie.errors import SendNotAllowedError
from acars_bridge.hoppie.requests import WeatherKind
from acars_bridge.services.session import build_session
from acars_bridge.services.wire_session import WireSessionVault


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


def test_vault_set_get_and_status_hides_logon():
    vault = WireSessionVault(ttl_seconds=60)
    assert vault.get() is None
    vault.update(logon="secret-wire", from_cs="SWR14", network_id="hoppie")
    creds = vault.get()
    assert creds is not None
    assert creds.logon == "secret-wire"
    assert creds.from_cs == "SWR14"
    status = vault.status_dict()
    assert status["ready"] is True
    assert status["from"] == "SWR14"
    assert "logon" not in status
    assert "secret" not in repr(vault)
    assert "secret" not in repr(creds)


def test_vault_ttl_expires():
    clock = {"t": 100.0}
    vault = WireSessionVault(ttl_seconds=60, now_fn=lambda: clock["t"])
    vault.update(logon="secret", from_cs="SWR14", network_id="hoppie")
    assert vault.get() is not None
    clock["t"] = 161.0
    assert vault.get() is None
    assert vault.status_dict()["ready"] is False


def test_vault_clear():
    vault = WireSessionVault()
    vault.update(logon="secret", from_cs="SWR14", network_id="hoppie")
    vault.clear()
    assert vault.get() is None


def test_outbound_uses_wire_vault_without_station(tmp_path, fixture_text):
    router = _Router(
        {
            "telex": "ok",
            "inforeq": fixture_text("inforeq_metar.txt"),
        }
    )
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(
        AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True
    )
    session.settings.set_companion_station_enabled(False)
    session.settings.set_callsign("")
    # No settings logon — wire vault only.
    session.wire_session.update(
        logon="wire-secret-logon", from_cs="DLH4MC", network_id="hoppie"
    )

    stored = session.outbound.send_telex("SWROPS", "HELLO VIA WIRE")
    assert stored.direction == "out"
    body = parse_qs(router.requests[0].content.decode())
    assert body["from"] == ["DLH4MC"]
    assert body["logon"] == ["wire-secret-logon"]
    assert body["type"] == ["telex"]

    rows = session.outbound.request_weather(WeatherKind.METAR, "EDDF")
    assert rows
    types = [parse_qs(r.content.decode())["type"][0] for r in router.requests]
    assert "inforeq" in types
    session.close()


def test_outbound_blocked_without_station_or_wire(tmp_path):
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    session.settings.set_companion_station_enabled(False)
    session.settings.set_hoppie_logon("settings-logon")
    session.settings.set_callsign("SWR14")
    with pytest.raises(SendNotAllowedError) as exc:
        session.outbound.send_telex("ATC", "hi")
    msg = str(exc.value).lower()
    assert "fenix" in msg or "hoppie" in msg
    assert "station" in msg
    session.close()


def test_tap_exchange_updates_wire_vault(tmp_path):
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    from acars_bridge.tap.service import TapService

    tap = TapService(session)
    tap.status.running = True
    tap._on_exchange(
        {
            "logon": "plane-secret",
            "from": "SWR99",
            "type": "poll",
            "to": "SWR99",
            "packet": "",
        },
        "ok",
    )
    creds = session.wire_session.get()
    assert creds is not None
    assert creds.logon == "plane-secret"
    assert creds.from_cs == "SWR99"
    assert tap.status.last_hoppie_error is None

    tap._on_exchange(
        {
            "logon": "plane-secret",
            "from": "SWR99",
            "type": "poll",
        },
        "error {invalid logon code}",
    )
    assert tap.status.last_hoppie_error is not None
    assert "invalid logon" in tap.status.last_hoppie_error.lower()

    tap._on_exchange(
        {
            "logon": "plane-secret",
            "from": "SWR99",
            "type": "poll",
        },
        "ok",
    )
    assert tap.status.last_hoppie_error is None
    tap.stop()
    assert session.wire_session.get() is None
    session.close()
