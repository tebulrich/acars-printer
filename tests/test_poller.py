from __future__ import annotations

import time
from urllib.parse import parse_qs

import httpx

from acars_bridge.config import AppPaths
from acars_bridge.hoppie.client import HoppieClient
from acars_bridge.hoppie.types import ClientMode
from acars_bridge.services.poller import BackgroundPoller
from acars_bridge.services.session import build_session


class _Router(httpx.BaseTransport):
    def __init__(self, body: str) -> None:
        self.body = body
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, text=self.body)


def test_background_poller_fetches_and_stores(tmp_path, fixture_text):
    router = _Router(fixture_text("cpdlc_short.txt"))
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(
        AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True
    )
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret")
    session.settings.set("poll_interval", "45")

    updates: list[int] = []
    poller = BackgroundPoller(
        session,
        on_update=lambda status: updates.append(1),
        on_new_messages=lambda n: None,
    )
    poller.start()
    poller.check_now()
    deadline = time.time() + 3
    while time.time() < deadline and not session.messages.list_recent(1):
        time.sleep(0.05)
    poller.stop()

    assert session.messages.list_recent(1)
    assert updates
    assert parse_qs(router.requests[0].content.decode())["type"][0] == "poll"
    session.close()


def test_observer_poller_uses_peek_not_poll(tmp_path, fixture_text):
    router = _Router(fixture_text("cpdlc_short.txt"))
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(
        AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True
    )
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret")
    session.settings.set_mode(ClientMode.OBSERVER)
    session.settings.set("poll_interval", "45")

    poller = BackgroundPoller(session)
    poller.start()
    poller.check_now()
    deadline = time.time() + 3
    while time.time() < deadline and not router.requests:
        time.sleep(0.05)
    poller.stop()

    assert router.requests
    assert parse_qs(router.requests[0].content.decode())["type"][0] == "peek"
    assert poller.status.last_hoppie_type == "peek"
    assert poller.status.last_mode == "observer"
    session.close()


def test_observer_callsign_in_use_message_does_not_ask_to_switch(tmp_path, fixture_text):
    router = _Router(fixture_text("callsign_in_use.txt"))
    client = HoppieClient("https://example.test/connect.html", transport=router)
    session = build_session(
        AppPaths.for_testing(tmp_path), client=client, use_fake_printer=True
    )
    session.settings.set_callsign("SWR14")
    session.settings.set_hoppie_logon("secret")
    session.settings.set_mode(ClientMode.OBSERVER)

    poller = BackgroundPoller(session)
    poller.start()
    poller.check_now()
    deadline = time.time() + 3
    while time.time() < deadline and not poller.status.last_error:
        time.sleep(0.05)
    poller.stop()

    assert poller.status.callsign_in_use
    assert poller.status.last_mode == "observer"
    assert "switch to Observer" not in (poller.status.last_error or "")
    assert "same" in (poller.status.last_error or "").lower()
    assert "logon" in (poller.status.last_error or "").lower()
    session.close()
