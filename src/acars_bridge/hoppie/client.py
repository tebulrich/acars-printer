from __future__ import annotations

from typing import Any

import httpx

from acars_bridge.config import HOPPIE_DEFAULT_URL, HOPPIE_TIMEOUT_SECONDS
from acars_bridge.hoppie.errors import HoppieError


class HoppieClient:
    """Thin HTTP transport for Hoppie connect.html. Never logs the logon code."""

    def __init__(
        self,
        base_url: str = HOPPIE_DEFAULT_URL,
        timeout_seconds: float = HOPPIE_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def request(self, fields: dict[str, str]) -> str:
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.post(
                    self.base_url,
                    data=fields,
                    headers={"Accept": "text/plain"},
                )
                response.raise_for_status()
                return response.text
        except httpx.TimeoutException as exc:
            raise HoppieError(f"Hoppie timeout after {self.timeout_seconds}s") from exc
        except httpx.HTTPError as exc:
            raise HoppieError(f"Hoppie HTTP error: {exc}") from exc

    def ping(self, logon: str, callsign: str) -> str:
        return self.request(
            {
                "logon": logon,
                "from": callsign or "ACARSBRIDGE",
                "to": "SERVER",
                "type": "ping",
                "packet": "",
            }
        )

    def poll(self, logon: str, callsign: str) -> str:
        return self.request(
            {
                "logon": logon,
                "from": callsign,
                "to": callsign,
                "type": "poll",
                "packet": "",
            }
        )

    def peek(self, logon: str, callsign: str) -> str:
        return self.request(
            {
                "logon": logon,
                "from": callsign,
                "to": callsign,
                "type": "peek",
                "packet": "",
            }
        )

    def send(
        self,
        *,
        logon: str,
        callsign: str,
        to: str,
        message_type: str,
        packet: str,
    ) -> str:
        return self.request(
            {
                "logon": logon,
                "from": callsign,
                "to": to,
                "type": message_type,
                "packet": packet,
            }
        )

    def close(self) -> None:
        # per-request clients; nothing persistent to close
        return None

    def __enter__(self) -> HoppieClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
