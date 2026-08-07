from __future__ import annotations

import ctypes
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
    # True/False when known from SimConnect; None when disconnected / not yet sampled.
    battery_on: bool | None = None
    # True when a main exit / interactive door is open; None when unknown.
    main_door_open: bool | None = None
    detail: str = ""


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


def bundled_dll_candidates() -> list[Path]:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "third_party" / "SimConnect" / "SimConnect.dll",
        Path(sys.executable).resolve().parent / "SimConnect" / "SimConnect.dll",
        Path(sys.executable).resolve().parent / "SimConnect.dll",
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
        candidates.insert(0, base / "SimConnect" / "SimConnect.dll")
        candidates.insert(1, base / "SimConnect.dll")
    return candidates


def is_elevated() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


class WindowsSimConnectMonitor:
    """Reads MSFS telemetry in-process via SimConnect.dll (works elevated too)."""

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
                log.info("SimConnect session ended: %s", exc)
                self._set(SimSnapshot(connected=False, detail=str(exc)))
            if self._stop.wait(self._reconnect_seconds):
                break

    def _session_loop(self) -> None:
        from acars_bridge.simconnect._ctypes_client import SimConnectSession

        dll_path = next((p for p in bundled_dll_candidates() if p.exists()), None)
        if dll_path is None:
            log.warning("SimConnect.dll not found — sterile / OFP sim gating inactive")
            self._set(SimSnapshot(connected=False, detail="SimConnect.dll not found"))
            self._stop.wait(max(self._reconnect_seconds, 30.0))
            return

        log.info("SimConnect opening in-process via %s", dll_path)
        with SimConnectSession(dll_path) as session:
            while not self._stop.is_set():
                snap = session.poll()
                if snap is None:
                    self._set(SimSnapshot(connected=False, detail="sim quit / session ended"))
                    break
                self._set(
                    SimSnapshot(
                        connected=snap.connected,
                        on_ground=snap.on_ground,
                        ground_velocity_kt=snap.ground_velocity_kt,
                        alt_agl_ft=snap.alt_agl_ft,
                        zulu_year=snap.zulu_year,
                        zulu_month=snap.zulu_month,
                        zulu_day=snap.zulu_day,
                        zulu_seconds=snap.zulu_seconds,
                        battery_on=snap.battery_on,
                        main_door_open=snap.main_door_open,
                        detail="inplace",
                    )
                )
                time.sleep(0.5)


def create_simconnect_monitor() -> SimConnectMonitor:
    if sys.platform != "win32":
        return NullSimConnectMonitor()
    return WindowsSimConnectMonitor()
