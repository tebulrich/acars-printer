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
    latitude: float | None = None
    longitude: float | None = None
    zulu_year: int | None = None
    zulu_month: int | None = None
    zulu_day: int | None = None
    zulu_seconds: float | None = None
    # "simconnect" | "xplane" when a backend produced this sample.
    source: str = ""
    # True/False when known from SimConnect; None when disconnected / not yet sampled.
    battery_on: bool | None = None
    # EXTERNAL POWER ON — GPU plugged in alone does not set this.
    external_power_on: bool | None = None
    # APU GENERATOR SWITCH — standard Asobo power source.
    apu_generator_on: bool | None = None
    # ELECTRICAL MAIN BUS VOLTAGE — aircraft-agnostic "systems powered" signal.
    main_bus_voltage: float | None = None
    # Every electrical SimVar we query (bus volts + switches) for debug logging.
    electrical: dict[str, float] | None = None
    # True when a main exit / interactive door is open; None when unknown.
    main_door_open: bool | None = None
    detail: str = ""


# Systems / source buses below this = cold. Never use battery/hot-battery bus
# volts — those stay live with the battery switch OFF on most airframes.
POWERED_BUS_VOLTS = 18.0


def aircraft_is_powered(snapshot: SimSnapshot | None) -> bool | None:
    """Whether the aircraft is electrically up for printing (GPU / APU / panel).

    Battery-master switches are never used — many airframes leave them ON (or
    report them) while cold and dark.

    Fenix / ``NEW ELECTRICAL SYSTEM`` airframes also leave ``ELECTRICAL MAIN
    BUS VOLTAGE`` and ``CIRCUIT AVIONICS ON`` stuck live with a dark cockpit,
    and never set stock ``EXTERNAL POWER ON``. For those we use Fenix L-vars:
    ``B_ELEC_BUS_POWER_DC_ESS`` (batteries feeding), EXT/APU lights, AC1/AC2.

    Legacy Asobo electrical still accepts main / genalt bus and circuit
    avionics.

    ``None`` means not connected / no usable electrical sample yet → gate holds.
    """
    if snapshot is None or not snapshot.connected:
        return None
    if snapshot.source == "xplane":
        return _xplane_is_powered(snapshot)

    elec = snapshot.electrical or {}

    def _num(key: str) -> float | None:
        if key in elec:
            try:
                return float(elec[key])
            except (TypeError, ValueError):
                return None
        return None

    def _on(*keys: str) -> bool:
        for key in keys:
            val = _num(key)
            if val is not None and val >= 0.5:
                return True
        return False

    def _bus_live(*keys: str) -> bool:
        for key in keys:
            val = _num(key)
            if val is not None and val >= POWERED_BUS_VOLTS:
                return True
        return False

    # Reliable across airframes: real power sources + systems that go dark cold.
    # Never use EXTERNAL POWER CONNECTION / AVAILABLE — those mean "GPU plugged
    # at the gate", not "EXT PWR selected on the overhead" (Fenix keeps
    # CONNECTION=1 after you deselect EXT).
    if snapshot.external_power_on is True or _on(
        "EXTERNAL POWER ON",
        "EXTERNAL POWER ON:1",
    ):
        return True
    if _bus_live(
        "ELECTRICAL EXTERNAL POWER VOLTAGE",
        "ELECTRICAL EXTERNAL POWER VOLTAGE:1",
    ):
        return True
    if snapshot.apu_generator_on is True or _on("APU GENERATOR SWITCH"):
        return True
    if _bus_live("APU VOLTS"):
        return True
    if _on("CIRCUIT GENERAL PANEL ON"):
        return True
    if _bus_live(
        "ELECTRICAL AVIONICS BUS VOLTAGE",
        "ELECTRICAL BUS VOLTAGE:1",
        "ELECTRICAL BUS VOLTAGE:2",
        "ELECTRICAL BUS VOLTAGE:3",
        "ELECTRICAL BUS VOLTAGE:4",
    ):
        return True

    # Fenix A32x L-vars (SU12+ SimConnect). Stock EXTERNAL POWER ON never flips.
    # DC ESS live = batteries actually feeding (stock BAT master can lie).
    # EXT green / APU GEN / AC1 / AC2 = external or generator power.
    if _on(
        "L:B_ELEC_BUS_POWER_DC_ESS",
        "L:I_OH_ELEC_EXT_PWR_L",
        "L:I_OH_ELEC_APU_GEN_L",
        "L:B_ELEC_BUS_POWER_AC1",
        "L:B_ELEC_BUS_POWER_AC2",
    ):
        return True

    new_elec = _num("NEW ELECTRICAL SYSTEM")
    fenix_class = new_elec is not None and new_elec >= 0.5

    if fenix_class:
        # MAIN BUS / CIRCUIT AVIONICS / GENALT / CONNECTION often lie.
        # If we already sampled the decisive vars and none fired → cold.
        decisive = (
            "EXTERNAL POWER ON",
            "EXTERNAL POWER ON:1",
            "ELECTRICAL EXTERNAL POWER VOLTAGE",
            "ELECTRICAL EXTERNAL POWER VOLTAGE:1",
            "APU GENERATOR SWITCH",
            "APU VOLTS",
            "CIRCUIT GENERAL PANEL ON",
            "ELECTRICAL AVIONICS BUS VOLTAGE",
            "ELECTRICAL BUS VOLTAGE:1",
            "ELECTRICAL BUS VOLTAGE:2",
            "ELECTRICAL BUS VOLTAGE:3",
            "ELECTRICAL BUS VOLTAGE:4",
            "L:B_ELEC_BUS_POWER_DC_ESS",
            "L:I_OH_ELEC_EXT_PWR_L",
            "L:I_OH_ELEC_APU_GEN_L",
            "L:B_ELEC_BUS_POWER_AC1",
            "L:B_ELEC_BUS_POWER_AC2",
        )
        if any(_num(k) is not None for k in decisive) or (
            snapshot.external_power_on is not None
            or snapshot.apu_generator_on is not None
        ):
            return False
        return None

    # Legacy electrical model (GA / older airliners).
    if _on("CIRCUIT AVIONICS ON"):
        return True

    legacy_buses = (
        "ELECTRICAL MAIN BUS VOLTAGE",
        "ELECTRICAL GENALT BUS VOLTAGE",
        "ELECTRICAL GENALT BUS VOLTAGE:1",
        "ELECTRICAL GENALT BUS VOLTAGE:2",
    )
    saw_bus = False
    for key in legacy_buses:
        val = _num(key)
        if val is None:
            continue
        saw_bus = True
        if val >= POWERED_BUS_VOLTS:
            return True

    if snapshot.main_bus_voltage is not None:
        saw_bus = True
        if snapshot.main_bus_voltage >= POWERED_BUS_VOLTS:
            return True

    panel = _num("CIRCUIT GENERAL PANEL ON")
    avionics = _num("CIRCUIT AVIONICS ON")
    if saw_bus or panel is not None or avionics is not None:
        return False

    return None


def _xplane_is_powered(snapshot: SimSnapshot) -> bool | None:
    """X-Plane power from real sources, not Laminar bus volts.

    On = engine running / N1, APU running / AVAIL / gen, or GPU relay.
    Off = those sources were sampled and all are dark (737 / A330 cold).
    Unknown = no source sample yet. Bus volts are ignored either way.
    """
    from acars_bridge.xplane.protocol import electrical_sources_live

    if snapshot.external_power_on is True or snapshot.apu_generator_on is True:
        return True
    return electrical_sources_live(snapshot.electrical)


class SimConnectMonitor(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def snapshot(self) -> SimSnapshot | None: ...


class CompositeSimMonitor:
    """Prefer MSFS SimConnect; fall back to X-Plane UDP (kinematics + generators)."""

    def __init__(
        self,
        primary: SimConnectMonitor,
        fallback: SimConnectMonitor,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    def start(self) -> None:
        self._primary.start()
        self._fallback.start()

    def stop(self) -> None:
        self._fallback.stop()
        self._primary.stop()

    def snapshot(self) -> SimSnapshot | None:
        primary = self._primary.snapshot()
        if primary is not None and primary.connected:
            return primary
        fallback = self._fallback.snapshot()
        if fallback is not None and fallback.connected:
            return fallback
        if fallback is not None and fallback.detail:
            return fallback
        return primary

    def set_xplane_endpoint(self, host: str, port: int | str) -> None:
        setter = getattr(self._fallback, "set_endpoint", None)
        if callable(setter):
            setter(host, port)


class NullSimConnectMonitor:
    """Always disconnected — used on non-Windows and when the DLL is unavailable."""

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def snapshot(self) -> SimSnapshot | None:
        return None


def bundled_dll_candidates() -> list[Path]:
    from acars_bridge.native_runtime import prepare_frozen_natives, simconnect_runtime_dir

    prepare_frozen_natives()
    here = Path(__file__).resolve()
    candidates = [
        simconnect_runtime_dir() / "SimConnect.dll",
        here.parents[3] / "third_party" / "SimConnect" / "SimConnect.dll",
        Path(sys.executable).resolve().parent / "SimConnect" / "SimConnect.dll",
        Path(sys.executable).resolve().parent / "SimConnect.dll",
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
        # Prefer stable LocalAppData copy (already first); MEIPASS is fallback only.
        candidates.append(base / "SimConnect" / "SimConnect.dll")
        candidates.append(base / "SimConnect.dll")
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
                # Must forward electrical / bus fields — a partial rebuild dropped them
                # and Only-when-powered never saw EXT power or main bus voltage.
                if snap.connected:
                    self._set(
                        SimSnapshot(
                            connected=True,
                            source=snap.source or "simconnect",
                            on_ground=snap.on_ground,
                            ground_velocity_kt=snap.ground_velocity_kt,
                            alt_agl_ft=snap.alt_agl_ft,
                            latitude=snap.latitude,
                            longitude=snap.longitude,
                            zulu_year=snap.zulu_year,
                            zulu_month=snap.zulu_month,
                            zulu_day=snap.zulu_day,
                            zulu_seconds=snap.zulu_seconds,
                            battery_on=snap.battery_on,
                            external_power_on=snap.external_power_on,
                            apu_generator_on=snap.apu_generator_on,
                            main_bus_voltage=snap.main_bus_voltage,
                            electrical=snap.electrical,
                            main_door_open=snap.main_door_open,
                            detail=snap.detail or "inplace",
                        )
                    )
                else:
                    self._set(snap)
                time.sleep(0.5)


def create_simconnect_monitor(settings: object | None = None) -> SimConnectMonitor:
    if sys.platform != "win32":
        return NullSimConnectMonitor()
    from acars_bridge.xplane.monitor import XPlaneUdpMonitor

    host = "127.0.0.1"
    port: int | str = 49000
    getter_h = getattr(settings, "xplane_host", None)
    getter_p = getattr(settings, "xplane_port", None)
    if callable(getter_h):
        host = str(getter_h())
    if callable(getter_p):
        port = getter_p()
    return CompositeSimMonitor(
        WindowsSimConnectMonitor(),
        XPlaneUdpMonitor(host=host, port=port),
    )
