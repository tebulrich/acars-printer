from __future__ import annotations

import random
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from acars_bridge.config import JITTER_SECONDS
from acars_bridge.hoppie.errors import CallsignInUseError, HoppieError
from acars_bridge.hoppie.types import ClientMode
from acars_bridge.services.backoff import delay_seconds
from acars_bridge.services.session import AppSession


@dataclass
class PollerStatus:
    running: bool = False
    last_check: datetime | None = None
    last_error: str | None = None
    last_stats: dict[str, int] = field(default_factory=dict)
    callsign_in_use: bool = False
    # Which Hoppie op was used on the last cycle (poll vs peek).
    last_mode: str | None = None
    last_hoppie_type: str | None = None


class BackgroundPoller:
    """Thread-safe Hoppie poll/peek loop for the desktop UI."""

    def __init__(
        self,
        session: AppSession,
        *,
        on_update: Callable[[PollerStatus], None] | None = None,
        on_new_messages: Callable[[int], None] | None = None,
    ) -> None:
        self._session = session
        self._on_update = on_update
        self._on_new_messages = on_new_messages
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.status = PollerStatus()
        self._failures = 0

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self.status.running = True
            self._thread = threading.Thread(target=self._loop, name="acars-poller", daemon=True)
            self._thread.start()
            self._emit()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)
        self.status.running = False
        self._emit()

    def check_now(self) -> None:
        self._wake.set()

    def _emit(self) -> None:
        if self._on_update:
            self._on_update(self.status)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._cycle()
            interval = self._session.settings.poll_interval()
            if self._failures:
                interval = delay_seconds(self._failures)
            else:
                interval += random.randint(0, JITTER_SECONDS)
            self._wake.wait(timeout=interval)
            self._wake.clear()

    def _cycle(self) -> None:
        logon = self._session.settings.hoppie_logon()
        callsign = self._session.settings.callsign()
        if not logon or not callsign:
            self.status.last_error = "Configure callsign and Hoppie logon in Settings."
            self._emit()
            return

        self.status.last_mode = ClientMode.OBSERVER.value
        self.status.last_hoppie_type = "peek"
        try:
            messages = self._session.observer.fetch(logon, callsign)
            stats = self._session.ingestion.ingest(messages)
            self.status.last_stats = stats
            self.status.last_error = None
            self.status.callsign_in_use = False
            self.status.last_check = datetime.now(UTC)
            self._failures = 0
            new_count = stats.get("printed", 0) + stats.get("stored", 0)
            if new_count and self._on_new_messages:
                self._on_new_messages(new_count)
        except CallsignInUseError as exc:
            self._failures += 1
            self.status.callsign_in_use = True
            self.status.last_check = datetime.now(UTC)
            # Peek fails when `from` is locked by a *different* logon.
            # Same-logon second clients (aircraft + this app) work.
            self.status.last_error = (
                f"Hoppie rejected peek for {callsign}: callsign locked "
                "by another logon. Use the *same* Hoppie logon as the aircraft "
                "client — not someone else's flight/account."
            )
            if str(exc) and str(exc) not in self.status.last_error:
                self.status.last_error = f"{self.status.last_error} ({exc})"
        except HoppieError as exc:
            self._failures += 1
            self.status.callsign_in_use = False
            self.status.last_error = str(exc)
            self.status.last_check = datetime.now(UTC)
        self._emit()
