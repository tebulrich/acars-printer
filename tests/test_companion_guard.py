from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

from acars_bridge.bridge.runtime import BridgeRuntime, FakeTapService
from acars_bridge.config import AppPaths
from acars_bridge.hoppie.client import HoppieClient
from acars_bridge.services.companion_guard import probe_station_callsign
from acars_bridge.services.session import build_session


class _Router(httpx.BaseTransport):
    def __init__(self, routes: dict[str, str] | None = None):
        self.routes = routes or {}
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        parsed = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        key = parsed.get("type", "")
        body = self.routes.get(key, "ok ")
        return httpx.Response(200, text=body)


def test_probe_station_ok(tmp_path, fixture_text):
    router = _Router({"poll": "ok "})
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(
        AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True
    )
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret")
    result = probe_station_callsign(session)
    assert result.ok is True
    assert result.conflict is False
    session.close()


def test_probe_station_callsign_in_use(tmp_path, fixture_text):
    router = _Router({"poll": fixture_text("callsign_in_use.txt")})
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(
        AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True
    )
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret")
    result = probe_station_callsign(session)
    assert result.ok is False
    assert result.conflict is True
    assert "already in use" in (result.reason or "").lower()
    session.close()


def test_save_settings_blocks_station_when_callsign_in_use(tmp_path, fixture_text):
    router = _Router({"poll": fixture_text("callsign_in_use.txt")})
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(
        AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True
    )
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret")
    session.settings.set_companion_enabled(True)
    runtime = BridgeRuntime(session, tap_factory=FakeTapService)
    try:
        result = runtime.handle(
            "save_settings",
            {"companion_station_enabled": True},
        )
        assert result["ok"] is True
        data = result["data"]
        assert data["companion_station_enabled"] is False
        assert data.get("station_blocked")
        assert "already in use" in data["station_blocked"].lower()
        assert session.settings.companion_station_enabled() is False
        assert runtime.companion_poller.running is False
    finally:
        runtime.shutdown()


def test_save_settings_allows_station_when_poll_ok(tmp_path):
    router = _Router({"poll": "ok "})
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(
        AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True
    )
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret")
    session.settings.set_companion_enabled(True)
    runtime = BridgeRuntime(session, tap_factory=FakeTapService)
    try:
        result = runtime.handle(
            "save_settings",
            {"companion_station_enabled": True},
        )
        assert result["ok"] is True
        data = result["data"]
        assert data["companion_station_enabled"] is True
        assert not data.get("station_blocked")
    finally:
        runtime.shutdown()
