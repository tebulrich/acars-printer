from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SimSnapshot:
    connected: bool
    on_ground: bool = True
    ground_velocity_kt: float = 0.0
    alt_agl_ft: float = 0.0
    zulu_year: int | None = None
    zulu_month: int | None = None
    zulu_day: int | None = None
    zulu_seconds: float | None = None


class SimConnectMonitor(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def snapshot(self) -> SimSnapshot | None: ...


class NullSimConnectMonitor:
    """Always disconnected — used on non-Windows and when the DLL is unavailable."""

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def snapshot(self) -> SimSnapshot | None:
        return None


def _bundled_dll_candidates() -> list[Path]:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "third_party" / "SimConnect" / "SimConnect.dll",
        Path(sys.executable).resolve().parent / "SimConnect" / "SimConnect.dll",
        Path(sys.executable).resolve().parent / "SimConnect.dll",
    ]
    # PyInstaller one-dir / frozen
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
        candidates.insert(0, base / "SimConnect" / "SimConnect.dll")
        candidates.insert(1, base / "SimConnect.dll")
    return candidates


class WindowsSimConnectMonitor:
    """Best-effort SimConnect reader for on-ground / GS / AGL / Zulu.

    Uses ctypes against bundled SimConnect.dll. If open/request fails, stays
    disconnected so sterile gating never blocks ACARS forever.
    """

    def __init__(self, *, reconnect_seconds: float = 5.0) -> None:
        self._reconnect_seconds = reconnect_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._snapshot: SimSnapshot | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="simconnect-monitor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        with self._lock:
            self._snapshot = None

    def snapshot(self) -> SimSnapshot | None:
        with self._lock:
            return self._snapshot

    def _set(self, snap: SimSnapshot | None) -> None:
        with self._lock:
            self._snapshot = snap

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._session_loop()
            except Exception as exc:  # pragma: no cover - depends on MSFS
                log.debug("SimConnect session ended: %s", exc)
                self._set(None)
            if self._stop.wait(self._reconnect_seconds):
                break

    def _session_loop(self) -> None:
        # Lazy import so non-Windows / test hosts never load ctypes SimConnect.
        from acars_bridge.simconnect._ctypes_client import SimConnectSession

        dll_path = next((p for p in _bundled_dll_candidates() if p.exists()), None)
        if dll_path is None:
            self._set(None)
            return

        with SimConnectSession(dll_path) as session:
            while not self._stop.is_set():
                snap = session.poll()
                self._set(snap)
                if snap is None or not snap.connected:
                    break
                time.sleep(0.5)


def create_simconnect_monitor() -> SimConnectMonitor:
    if sys.platform != "win32":
        return NullSimConnectMonitor()
    return WindowsSimConnectMonitor()
