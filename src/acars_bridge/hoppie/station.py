from __future__ import annotations

from acars_bridge.hoppie.client import HoppieClient
from acars_bridge.hoppie.errors import HoppieError
from acars_bridge.hoppie.parser import parse_response
from acars_bridge.hoppie.types import HoppieMessage


class StationTransport:
    """Owns the callsign via poll; may send telex/CPDLC."""

    def __init__(self, client: HoppieClient) -> None:
        self._client = client

    def fetch(self, logon: str, callsign: str) -> list[HoppieMessage]:
        callsign = callsign.strip().upper()
        if not callsign:
            raise HoppieError("Callsign is required.")
        if not logon.strip():
            raise HoppieError("Hoppie logon code is required.")
        raw = self._client.poll(logon, callsign)
        return parse_response(raw, callsign)

    def send_telex(self, logon: str, callsign: str, to: str, text: str) -> str:
        return self._client.send(
            logon=logon,
            callsign=callsign.strip().upper(),
            to=to.strip().upper(),
            message_type="telex",
            packet=text,
        )

    def send_cpdlc(self, logon: str, callsign: str, to: str, packet: str) -> str:
        return self._client.send(
            logon=logon,
            callsign=callsign.strip().upper(),
            to=to.strip().upper(),
            message_type="cpdlc",
            packet=packet,
        )

    def send_inforeq(self, logon: str, callsign: str, packet: str) -> str:
        return self._client.send(
            logon=logon,
            callsign=callsign.strip().upper(),
            to="SERVER",
            message_type="inforeq",
            packet=packet,
        )

    def send_position(self, logon: str, callsign: str, to: str, packet: str) -> str:
        return self._client.send(
            logon=logon,
            callsign=callsign.strip().upper(),
            to=to.strip().upper(),
            message_type="position",
            packet=packet,
        )

    def ping(self, logon: str, callsign: str) -> bool:
        raw = self._client.ping(logon, callsign.strip().upper())
        return raw.strip().lower().startswith("ok")
