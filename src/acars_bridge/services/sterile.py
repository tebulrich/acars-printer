from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from acars_bridge.simconnect.monitor import SimSnapshot

log = logging.getLogger(__name__)

# Defaults from product plan.
STERILE_GS_KT = 40.0
STERILE_AGL_FT = 1500.0
MAX_QUEUE_PER_CHANNEL = 40
FLUSH_STAGGER_SECONDS = 0.45


@dataclass(frozen=True, slots=True)
class SterileThresholds:
    gs_kt: float = STERILE_GS_KT
    agl_ft: float = STERILE_AGL_FT


def compute_sterile(
    snapshot: SimSnapshot | None,
    *,
    thresholds: SterileThresholds | None = None,
) -> bool:
    """Return True when printing should be muted for sterile cockpit.

    When SimConnect is disconnected (snapshot is None), returns False so ACARS
    is never blocked indefinitely.
    """
    if snapshot is None or not snapshot.connected:
        return False
    limits = thresholds or SterileThresholds()
    if snapshot.on_ground and snapshot.ground_velocity_kt >= limits.gs_kt:
        return True
    if (not snapshot.on_ground) and snapshot.alt_agl_ft < limits.agl_ft:
        return True
    return False


PrintJob = Callable[[], None]
FlushRunner = Callable[[PrintJob], None]


class SterileGate:
    """Shared sterile gate with deferred print queues for ACARS and SimBrief."""

    def __init__(
        self,
        *,
        thresholds: SterileThresholds | None = None,
        max_queue: int = MAX_QUEUE_PER_CHANNEL,
        flush_stagger_seconds: float = FLUSH_STAGGER_SECONDS,
    ) -> None:
        self._thresholds = thresholds or SterileThresholds()
        self._max_queue = max(1, max_queue)
        self._flush_stagger_seconds = max(0.0, flush_stagger_seconds)
        self._lock = threading.Lock()
        self._sterile = False
        self._acars_queue: list[PrintJob] = []
        self._simbrief_queue: list[PrintJob] = []
        self._listeners: list[Callable[[bool], None]] = []
        self._flush_runner: FlushRunner | None = None
        self._dropped = 0

    def set_flush_runner(self, runner: FlushRunner | None) -> None:
        """Optional async runner for flush jobs (keeps UI thread free)."""
        self._flush_runner = runner

    @property
    def is_sterile(self) -> bool:
        with self._lock:
            return self._sterile

    @property
    def thresholds(self) -> SterileThresholds:
        with self._lock:
            return self._thresholds

    @property
    def dropped_count(self) -> int:
        with self._lock:
            return self._dropped

    def set_thresholds(self, thresholds: SterileThresholds) -> None:
        with self._lock:
            self._thresholds = thresholds

    def add_listener(self, callback: Callable[[bool], None]) -> None:
        self._listeners.append(callback)

    def update_from_snapshot(self, snapshot: SimSnapshot | None) -> None:
        with self._lock:
            thresholds = self._thresholds
        sterile = compute_sterile(snapshot, thresholds=thresholds)
        flush_acars: list[PrintJob] = []
        flush_simbrief: list[PrintJob] = []
        changed = False
        with self._lock:
            if sterile == self._sterile:
                return
            changed = True
            was_sterile = self._sterile
            self._sterile = sterile
            if was_sterile and not sterile:
                flush_acars = self._acars_queue
                flush_simbrief = self._simbrief_queue
                self._acars_queue = []
                self._simbrief_queue = []
        if changed:
            for listener in list(self._listeners):
                try:
                    listener(sterile)
                except Exception:
                    log.debug("sterile listener failed", exc_info=True)
        combined = flush_acars + flush_simbrief
        for index, job in enumerate(combined):
            self._dispatch_flush(job, delay=index * self._flush_stagger_seconds)

    def _dispatch_flush(self, job: PrintJob, *, delay: float) -> None:
        def wrapped() -> None:
            if delay > 0:
                time.sleep(delay)
            try:
                job()
            except Exception:
                log.exception("sterile flush job failed")

        runner = self._flush_runner
        if runner is not None:
            runner(wrapped)
        else:
            wrapped()

    def run_or_defer_acars(self, job: PrintJob) -> bool:
        """Run immediately or queue. Returns True if deferred."""
        with self._lock:
            if self._sterile:
                self._enqueue(self._acars_queue, job)
                return True
        job()
        return False

    def run_or_defer_simbrief(self, job: PrintJob) -> bool:
        """Run immediately or queue. Returns True if deferred."""
        with self._lock:
            if self._sterile:
                self._enqueue(self._simbrief_queue, job)
                return True
        job()
        return False

    def _enqueue(self, queue: list[PrintJob], job: PrintJob) -> None:
        if len(queue) >= self._max_queue:
            queue.pop(0)
            self._dropped += 1
            log.warning("sterile queue full — dropped oldest deferred print")
        queue.append(job)

    def queue_sizes(self) -> tuple[int, int]:
        with self._lock:
            return len(self._acars_queue), len(self._simbrief_queue)
