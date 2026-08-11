"""Ephemeral Hoppie credentials captured from Connect/tap MITM (RAM only)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


DEFAULT_WIRE_TTL_SECONDS = 20 * 60


@dataclass(frozen=True, slots=True)
class WireSessionCreds:
    logon: str
    from_cs: str
    network_id: str
    seen_at: float

    def __repr__(self) -> str:
        return (
            f"WireSessionCreds(from_cs={self.from_cs!r}, network_id={self.network_id!r}, "
            f"seen_at={self.seen_at!r}, logon='***')"
        )


class WireSessionVault:
    """Thread-safe in-memory vault for plane↔Hoppie credentials.

    Never persists to settings. Status dicts must not include the logon.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_WIRE_TTL_SECONDS,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._ttl = max(30.0, float(ttl_seconds))
        self._now = now_fn or time.monotonic
        self._lock = threading.Lock()
        self._creds: WireSessionCreds | None = None

    def __repr__(self) -> str:
        with self._lock:
            ready = self._creds is not None and self._fresh_unlocked(self._creds)
            from_cs = self._creds.from_cs if self._creds else None
        return f"WireSessionVault(ready={ready}, from_cs={from_cs!r})"

    def update(
        self,
        *,
        logon: str,
        from_cs: str,
        network_id: str,
    ) -> None:
        cleaned_logon = (logon or "").strip()
        cleaned_from = (from_cs or "").strip().upper()
        if not cleaned_logon or not cleaned_from:
            return
        if cleaned_from in {"UNKNOWN", "SERVER", "N/A"}:
            return
        with self._lock:
            self._creds = WireSessionCreds(
                logon=cleaned_logon,
                from_cs=cleaned_from,
                network_id=(network_id or "").strip() or "unknown",
                seen_at=self._now(),
            )

    def get(self) -> WireSessionCreds | None:
        with self._lock:
            creds = self._creds
            if creds is None or not self._fresh_unlocked(creds):
                if creds is not None:
                    self._creds = None
                return None
            return creds

    def clear(self) -> None:
        with self._lock:
            self._creds = None

    def clear_if_network(self, network_id: str) -> None:
        """Clear when the ACARS network profile changes."""
        with self._lock:
            if self._creds is not None and self._creds.network_id != network_id:
                self._creds = None

    def active_logon(self) -> str | None:
        creds = self.get()
        return creds.logon if creds else None

    def status_dict(self) -> dict[str, object]:
        creds = self.get()
        if creds is None:
            return {"ready": False, "from": "", "age_s": None, "network_id": ""}
        age = max(0, int(self._now() - creds.seen_at))
        return {
            "ready": True,
            "from": creds.from_cs,
            "age_s": age,
            "network_id": creds.network_id,
        }

    def _fresh_unlocked(self, creds: WireSessionCreds) -> bool:
        return (self._now() - creds.seen_at) <= self._ttl
