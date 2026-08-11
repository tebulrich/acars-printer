"""Opt-in Hoppie station poll loop for the phone companion."""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from acars_bridge.hoppie.errors import CallsignInUseError, HoppieError
from acars_bridge.services.station_identity import resolve_station_identity

if TYPE_CHECKING:
    from acars_bridge.services.session import AppSession

log = logging.getLogger(__name__)


class CompanionStationPoller:
    """Poll Hoppie as the configured callsign while companion station is on."""

    def __init__(
        self,
        session: AppSession,
        *,
        on_ingest: Callable[[int], None] | None = None,
        on_callsign_conflict: Callable[[str], None] | None = None,
    ) -> None:
        self._session = session
        self._on_ingest = on_ingest
        self._on_callsign_conflict = on_callsign_conflict
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None
        self.last_poll_at: float | None = None
        self.last_message_count: int = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="companion-station-poll", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            settings = self._session.settings
            if not (
                settings.companion_enabled() and settings.companion_station_enabled()
            ):
                self._stop.wait(2.0)
                continue
            logon = settings.hoppie_logon()
            callsign = resolve_station_identity(self._session).callsign
            if not logon or not callsign:
                self.last_error = (
                    "Set Hoppie logon under Network. Callsign auto-follows "
                    "SimBrief / last ACARS, or set the Network filter."
                )
                self._stop.wait(5.0)
                continue
            try:
                messages = self._session.station.fetch(logon, callsign)
                if messages:
                    stats = self._session.ingestion.ingest(messages)
                    stored = int(stats.get("stored", 0) or 0)
                    self.last_message_count = stored
                    if stored and self._on_ingest is not None:
                        try:
                            self._on_ingest(stored)
                        except Exception:  # noqa: BLE001
                            log.exception("companion station on_ingest failed")
                self.last_error = None
                self.last_poll_at = time.time()
            except CallsignInUseError as exc:
                msg = (
                    f"Callsign already in use on Hoppie — station mode turned off. "
                    f"Keep using Connect/tap (aircraft owns the callsign). ({exc})"
                )
                self.last_error = msg
                log.warning("companion station: %s", exc)
                settings.set_companion_station_enabled(False)
                if self._on_callsign_conflict is not None:
                    try:
                        self._on_callsign_conflict(msg)
                    except Exception:  # noqa: BLE001
                        log.exception("companion station on_callsign_conflict failed")
                self._stop.wait(5.0)
                continue
            except HoppieError as exc:
                self.last_error = str(exc)
                log.warning("companion station hoppie: %s", exc)
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                log.exception("companion station poll failed")
            # Hoppie recommends 45–75s random poll cadence.
            self._stop.wait(random.uniform(45.0, 75.0))
