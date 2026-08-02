from __future__ import annotations

from acars_bridge.hoppie.client import HoppieClient
from acars_bridge.hoppie.errors import HoppieError, SendNotAllowedError
from acars_bridge.hoppie.parser import parse_response
from acars_bridge.hoppie.types import HoppieMessage


class ObserverTransport:
    """Non-destructive peek observer. Send is always rejected."""

    def __init__(self, client: HoppieClient) -> None:
        self._client = client

    def fetch(self, logon: str, callsign: str) -> list[HoppieMessage]:
        callsign = callsign.strip().upper()
        if not callsign:
            raise HoppieError("Callsign is required.")
        if not logon.strip():
            raise HoppieError("Hoppie logon code is required.")
        raw = self._client.peek(logon, callsign)
        return parse_response(raw, callsign)

    def send_telex(self, *args: object, **kwargs: object) -> str:
        raise SendNotAllowedError(
            "Observer mode cannot send. Switch to Station mode "
            "(and stop the aircraft Hoppie client) to own the callsign."
        )

    def send_cpdlc(self, *args: object, **kwargs: object) -> str:
        raise SendNotAllowedError(
            "Observer mode cannot send. Switch to Station mode "
            "(and stop the aircraft Hoppie client) to own the callsign."
        )

    def send_inforeq(self, *args: object, **kwargs: object) -> str:
        raise SendNotAllowedError(
            "Observer mode cannot send. Switch to Station mode first."
        )

    def send_position(self, *args: object, **kwargs: object) -> str:
        raise SendNotAllowedError(
            "Observer mode cannot send. Switch to Station mode first."
        )

    def ping(self, logon: str, callsign: str) -> bool:
        raw = self._client.ping(logon, callsign.strip().upper())
        return raw.strip().lower().startswith("ok")
