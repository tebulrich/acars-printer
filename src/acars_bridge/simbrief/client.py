from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import httpx

from acars_bridge.simbrief.models import SimBriefFlightPlan

SIMBRIEF_FETCH_URL = "https://www.simbrief.com/api/xml.fetcher.php"


class SimBriefError(Exception):
    """SimBrief fetch or parse failure."""


class SimBriefClient:
    def __init__(
        self,
        *,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._timeout = timeout
        self._transport = transport

    def fetch_latest(self, user_identifier: str) -> SimBriefFlightPlan:
        user = (user_identifier or "").strip()
        if not user:
            raise SimBriefError("Enter your SimBrief username or pilot ID first.")

        param = "userid" if user.isdigit() else "username"
        url = f"{SIMBRIEF_FETCH_URL}?{param}={quote(user)}&json=1"

        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.get(url)
        except httpx.HTTPError as exc:
            raise SimBriefError(f"Could not reach SimBrief (network error): {exc}") from exc

        if response.status_code >= 400:
            raise SimBriefError(
                f"SimBrief returned HTTP {response.status_code}. Check your username/ID."
            )

        try:
            payload: Any = response.json()
        except json.JSONDecodeError as exc:
            raise SimBriefError("SimBrief returned invalid JSON.") from exc

        if not isinstance(payload, dict):
            raise SimBriefError("SimBrief returned unexpected JSON shape.")

        fetch = payload.get("fetch")
        if isinstance(fetch, dict):
            status = str(fetch.get("status") or "")
            if status and "success" not in status.lower():
                raise SimBriefError(f"SimBrief error: {status}")

        return SimBriefFlightPlan.from_json(payload)
