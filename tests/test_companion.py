from __future__ import annotations

import socket
import time
from urllib.parse import parse_qs

import httpx
import pytest

from acars_bridge.bridge.runtime import BridgeRuntime, FakeTapService
from acars_bridge.companion.auth import token_ok
from acars_bridge.config import AppPaths
from acars_bridge.hoppie.client import HoppieClient
from acars_bridge.hoppie.errors import SendNotAllowedError
from acars_bridge.hoppie.requests import WeatherKind
from acars_bridge.hoppie.types import HoppieMessage, MessageType
from acars_bridge.services.session import build_session


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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_http(url: str, *, timeout: float = 3.0) -> None:
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            httpx.get(url, timeout=0.4)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.05)
    raise AssertionError(f"server did not start: {last}")


def test_token_ok_constant_time():
    assert token_ok("abc", "abc")
    assert not token_ok("abc", "abd")
    assert not token_ok(None, "abc")
    assert not token_ok("abc", "")


def test_outbound_unlocked_when_companion_station_on(tmp_path, fixture_text):
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
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret-logon-code")
    session.settings.set_companion_station_enabled(True)

    stored = session.outbound.send_telex("SWROPS", "HELLO FROM PHONE")
    assert stored.direction == "out"
    assert "HELLO FROM PHONE" in stored.normalized_body

    rows = session.outbound.request_weather(WeatherKind.METAR, "EGLL")
    assert rows
    types = [parse_qs(r.content.decode())["type"][0] for r in router.requests]
    assert "telex" in types
    assert "inforeq" in types
    session.close()


def test_companion_http_open_on_lan(tmp_path):
    port = _free_port()
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret-logon-code")
    session.settings.set_companion_enabled(True)
    session.settings.set_companion_station_enabled(False)
    session.settings.set_companion_port(port)

    session.messages.insert_inbound(
        HoppieMessage(
            callsign="SWR14",
            sender="SWROPS",
            recipient="SWR14",
            message_type=MessageType.TELEX,
            raw_payload="OPS CHECK",
            normalized_body="OPS CHECK",
        ),
        fingerprint="test-ops-check-1",
    )

    runtime = BridgeRuntime(session, tap_factory=FakeTapService)
    try:
        assert runtime.companion_server.running
        base = f"http://127.0.0.1:{port}"
        _wait_http(f"{base}/")

        ok = httpx.get(f"{base}/api/status", timeout=2.0)
        assert ok.status_code == 200
        payload = ok.json()
        assert payload["callsign"] == "SWR14"
        assert payload["message_count"] >= 1
        assert "?token=" not in (payload.get("url") or "")

        inbox = httpx.get(f"{base}/api/messages?limit=20", timeout=2.0)
        assert inbox.status_code == 200
        messages = inbox.json()["messages"]
        assert any("OPS CHECK" in (m.get("preview") or "") for m in messages)

        page = httpx.get(f"{base}/", timeout=2.0)
        assert page.status_code == 200
        assert "ACARS Companion" in page.text
    finally:
        runtime.shutdown()


def test_companion_send_blocked_without_station(tmp_path):
    port = _free_port()
    router = _Router({"telex": "ok"})
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(
        AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True
    )
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret-logon-code")
    session.settings.set_companion_enabled(True)
    session.settings.set_companion_station_enabled(False)
    session.settings.set_companion_port(port)

    runtime = BridgeRuntime(session, tap_factory=FakeTapService)
    try:
        base = f"http://127.0.0.1:{port}"
        _wait_http(f"{base}/")
        res = httpx.post(
            f"{base}/api/telex",
            json={"to": "SWROPS", "text": "NOPE"},
            timeout=2.0,
        )
        assert res.status_code == 403
        assert not router.requests
    finally:
        runtime.shutdown()


def test_companion_telex_wx_and_pdc_when_station_on(tmp_path, fixture_text):
    port = _free_port()
    router = _Router(
        {
            "telex": "ok",
            "inforeq": fixture_text("inforeq_metar.txt"),
            "poll": "ok ",
        }
    )
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(
        AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True
    )
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret-logon-code")
    session.settings.set_companion_enabled(True)
    # Station off at boot so poller does not race the HTTP assertions.
    session.settings.set_companion_station_enabled(False)
    session.settings.set_companion_port(port)

    runtime = BridgeRuntime(session, tap_factory=FakeTapService)
    try:
        session.settings.set_companion_station_enabled(True)
        base = f"http://127.0.0.1:{port}"
        _wait_http(f"{base}/")

        telex = httpx.post(
            f"{base}/api/telex",
            json={"to": "SWROPS", "text": "HELLO"},
            timeout=3.0,
        )
        assert telex.status_code == 200, telex.text
        assert telex.json()["ok"] is True

        wx = httpx.post(
            f"{base}/api/weather",
            json={"kind": "metar", "icao": "EGLL"},
            timeout=3.0,
        )
        assert wx.status_code == 200, wx.text

        atis = httpx.post(
            f"{base}/api/atis",
            json={"icao": "EGLL", "side": "dep", "source": "vatatis"},
            timeout=3.0,
        )
        assert atis.status_code == 200, atis.text

        pdc = httpx.post(
            f"{base}/api/pdc",
            json={
                "station": "EGLL",
                "departure": "EGLL",
                "destination": "LFPG",
                "aircraft_type": "A320",
                "stand": "201",
                "atis_letter": "B",
            },
            timeout=3.0,
        )
        assert pdc.status_code == 200, pdc.text

        bodies = [parse_qs(r.content.decode()) for r in router.requests]
        telex_packets = [
            b.get("packet", [""])[0] for b in bodies if b.get("type") == ["telex"]
        ]
        assert any("HELLO" in p for p in telex_packets)
        assert any("REQUEST PREDEP CLEARANCE" in p for p in telex_packets)
        assert any(
            b.get("type") == ["inforeq"] and "metar EGLL" in b.get("packet", [""])[0]
            for b in bodies
        )
        assert any(
            b.get("type") == ["inforeq"]
            and "vatatis EGLL_D_ATIS" in b.get("packet", [""])[0]
            for b in bodies
        )
    finally:
        runtime.shutdown()


def test_companion_reprint_and_cpdlc_reply(tmp_path):
    port = _free_port()
    router = _Router({"cpdlc": "ok"})
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(
        AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True
    )
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret-logon-code")
    session.settings.set_companion_enabled(True)
    session.settings.set_companion_station_enabled(True)
    session.settings.set_companion_port(port)

    stored = session.messages.insert_inbound(
        HoppieMessage(
            callsign="SWR14",
            sender="LSAS_CTR",
            recipient="SWR14",
            message_type=MessageType.CPDLC,
            raw_payload="{LSAS_CTR cpdlc {/data2/15//WU/CLIMB}}",
            normalized_body="CLIMB TO FL360",
            min=15,
            ra="WU",
        ),
        fingerprint="test-cpdlc-wu-1",
    )
    assert stored is not None

    runtime = BridgeRuntime(session, tap_factory=FakeTapService)
    try:
        base = f"http://127.0.0.1:{port}"
        _wait_http(f"{base}/")

        detail = httpx.get(f"{base}/api/messages/{stored.id}", timeout=2.0)
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["can_reply"] is True
        assert "WILCO" in payload["reply_choices"]

        printed = httpx.post(
            f"{base}/api/messages/{stored.id}/print",
            json={},
            timeout=3.0,
        )
        assert printed.status_code == 200, printed.text
        assert printed.json()["ok"] is True
        assert session.print_manager._printer.printed

        wilco = httpx.post(
            f"{base}/api/messages/{stored.id}/reply",
            json={"reply": "WILCO"},
            timeout=3.0,
        )
        assert wilco.status_code == 200, wilco.text
        assert wilco.json()["ok"] is True
        bodies = [parse_qs(r.content.decode()) for r in router.requests]
        assert any(
            b.get("type") == ["cpdlc"] and "WILCO" in b.get("packet", [""])[0]
            for b in bodies
        )
    finally:
        runtime.shutdown()


def test_session_outbound_still_blocked_by_default(tmp_path):
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret")
    with pytest.raises(SendNotAllowedError):
        session.outbound.send_telex("ATC", "hi")
    session.close()
