from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
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


def compute_unpowered(
    snapshot: SimSnapshot | None,
    *,
    require_powered: bool,
) -> bool:
    """True when prints should wait for aircraft battery power.

    Only holds when the setting is on AND SimConnect reports battery off.
    Disconnected / unknown battery does not block (same idea as sterile).
    """
    if not require_powered:
        return False
    if snapshot is None or not snapshot.connected:
        return False
    if snapshot.battery_on is None:
        return False
    return not snapshot.battery_on


PrintJob = Callable[[], None]
FlushRunner = Callable[[PrintJob], None]


class SterileGate:
    """Shared print gate with deferred queues for ACARS and SimBrief.

    Holds prints while sterile and/or (optionally) while battery is off.
    """

    def __init__(
        self,
        *,
        thresholds: SterileThresholds | None = None,
        require_powered: bool = False,
        max_queue: int = MAX_QUEUE_PER_CHANNEL,
        flush_stagger_seconds: float = FLUSH_STAGGER_SECONDS,
    ) -> None:
        self._thresholds = thresholds or SterileThresholds()
        self._require_powered = bool(require_powered)
        self._max_queue = max(1, max_queue)
        self._flush_stagger_seconds = max(0.0, flush_stagger_seconds)
        self._lock = threading.Lock()
        self._sterile = False
        self._unpowered = False
        self._blocking = False
        self._battery_on: bool | None = None
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
    def is_unpowered(self) -> bool:
        with self._lock:
            return self._unpowered

    @property
    def is_blocking(self) -> bool:
        """True when new prints should be queued (sterile and/or battery off)."""
        with self._lock:
            return self._blocking

    @property
    def battery_on(self) -> bool | None:
        with self._lock:
            return self._battery_on

    @property
    def require_powered(self) -> bool:
        with self._lock:
            return self._require_powered

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

    def set_require_powered(self, enabled: bool) -> None:
        with self._lock:
            self._require_powered = bool(enabled)

    def add_listener(self, callback: Callable[[bool], None]) -> None:
        self._listeners.append(callback)

    def block_reason(self) -> str:
        """Short reason for UI: '', 'sterile', 'unpowered', or 'sterile+unpowered'."""
        with self._lock:
            if not self._blocking:
                return ""
            parts: list[str] = []
            if self._sterile:
                parts.append("sterile")
            if self._unpowered:
                parts.append("unpowered")
            return "+".join(parts) if parts else "blocked"

    def update_from_snapshot(self, snapshot: SimSnapshot | None) -> None:
        with self._lock:
            thresholds = self._thresholds
            require_powered = self._require_powered
        sterile = compute_sterile(snapshot, thresholds=thresholds)
        unpowered = compute_unpowered(snapshot, require_powered=require_powered)
        battery_on = (
            snapshot.battery_on
            if snapshot is not None and snapshot.connected
            else None
        )
        blocking = sterile or unpowered
        flush_acars: list[PrintJob] = []
        flush_simbrief: list[PrintJob] = []
        sterile_changed = False
        with self._lock:
            was_blocking = self._blocking
            was_sterile = self._sterile
            self._sterile = sterile
            self._unpowered = unpowered
            self._battery_on = battery_on
            self._blocking = blocking
            sterile_changed = sterile != was_sterile
            if was_blocking and not blocking:
                flush_acars = self._acars_queue
                flush_simbrief = self._simbrief_queue
                self._acars_queue = []
                self._simbrief_queue = []
            elif was_blocking == blocking and not sterile_changed:
                return
        if sterile_changed:
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
            if self._blocking:
                self._enqueue(self._acars_queue, job)
                return True
        job()
        return False

    def run_or_defer_simbrief(self, job: PrintJob) -> bool:
        """Run immediately or queue. Returns True if deferred."""
        with self._lock:
            if self._blocking:
                self._enqueue(self._simbrief_queue, job)
                return True
        job()
        return False

    def _enqueue(self, queue: list[PrintJob], job: PrintJob) -> None:
        if len(queue) >= self._max_queue:
            queue.pop(0)
            self._dropped += 1
            log.warning("print queue full — dropped oldest deferred print")
        queue.append(job)

    def queue_sizes(self) -> tuple[int, int]:
        with self._lock:
            return len(self._acars_queue), len(self._simbrief_queue)
