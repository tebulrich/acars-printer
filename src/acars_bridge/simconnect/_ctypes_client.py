"""Minimal ctypes SimConnect session for MSFS user aircraft telemetry.

Intentionally small: open, define a few vars, request per-second data, poll.
Failures leave the monitor disconnected (caller treats that as non-sterile).
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_bool,
    c_char_p,
    c_float,
    c_int,
    c_long,
    c_uint32,
    c_void_p,
)
from pathlib import Path

from acars_bridge.simconnect.monitor import SimSnapshot

log = logging.getLogger(__name__)

# HRESULT
S_OK = 0

# SIMCONNECT_DATATYPE
SIMCONNECT_DATATYPE_FLOAT64 = 4

# SIMCONNECT_PERIOD
SIMCONNECT_PERIOD_SECOND = 3

SIMCONNECT_OBJECT_ID_USER = 0
SIMCONNECT_UNUSED = 0xFFFFFFFF

# Recv ids — must match SimConnect.h (NULL=0, EXCEPTION=1, OPEN=2, QUIT=3, …)
SIMCONNECT_RECV_ID_NULL = 0
SIMCONNECT_RECV_ID_EXCEPTION = 1
SIMCONNECT_RECV_ID_OPEN = 2
SIMCONNECT_RECV_ID_QUIT = 3
SIMCONNECT_RECV_ID_SIMOBJECT_DATA = 8

_EXCEPTION_NAMES = {
    1: "ERROR",
    2: "SIZE_MISMATCH",
    3: "UNRECOGNIZED_ID",
    4: "UNOPENED",
    5: "VERSION_MISMATCH",
    6: "TOO_MANY_GROUPS",
    7: "NAME_UNRECOGNIZED",
    17: "INVALID_DATA_TYPE",
    18: "INVALID_DATA_SIZE",
    19: "DATA_ERROR",
    27: "DEFINITION_ERROR",
}


class SIMCONNECT_RECV(Structure):
    _pack_ = 1
    _fields_ = [
        ("dwSize", c_uint32),
        ("dwVersion", c_uint32),
        ("dwID", c_uint32),
    ]


class SIMCONNECT_RECV_SIMOBJECT_DATA(Structure):
    """Header only — variable telemetry payload starts immediately after.

    Layout matches MSFS SimConnect.h (pack 1). There is no dwObjectType field.
    """

    _pack_ = 1
    _fields_ = [
        ("dwSize", c_uint32),
        ("dwVersion", c_uint32),
        ("dwID", c_uint32),
        ("dwRequestID", c_uint32),
        ("dwObjectID", c_uint32),
        ("dwDefineID", c_uint32),
        ("dwFlags", c_uint32),
        ("dwentrynumber", c_uint32),
        ("dwoutof", c_uint32),
        ("dwDefineCount", c_uint32),
    ]


class SIMCONNECT_RECV_EXCEPTION(Structure):
    _pack_ = 1
    _fields_ = [
        ("dwSize", c_uint32),
        ("dwVersion", c_uint32),
        ("dwID", c_uint32),
        ("dwException", c_uint32),
        ("dwSendID", c_uint32),
        ("dwIndex", c_uint32),
    ]


class TelemetryData(Structure):
    _fields_ = [
        ("on_ground", ctypes.c_double),
        ("ground_velocity", ctypes.c_double),
        ("alt_agl", ctypes.c_double),
        ("latitude", ctypes.c_double),
        ("longitude", ctypes.c_double),
        ("zulu_year", ctypes.c_double),
        ("zulu_month", ctypes.c_double),
        ("zulu_day", ctypes.c_double),
        ("zulu_seconds", ctypes.c_double),
        ("battery_master", ctypes.c_double),
        ("battery_master_1", ctypes.c_double),
        ("battery_master_2", ctypes.c_double),
        ("exit_open_0", ctypes.c_double),
        ("exit_open_1", ctypes.c_double),
        ("interactive_open_0", ctypes.c_double),
        ("interactive_open_1", ctypes.c_double),
        # --- electrical buses / sources (logged in full every sample) ---
        ("bus_main", ctypes.c_double),
        ("bus_avionics", ctypes.c_double),
        ("bus_battery", ctypes.c_double),
        ("bus_hot_battery", ctypes.c_double),
        ("bus_genalt", ctypes.c_double),
        ("bus_genalt_1", ctypes.c_double),
        ("bus_genalt_2", ctypes.c_double),
        ("bus_indexed_1", ctypes.c_double),
        ("bus_indexed_2", ctypes.c_double),
        ("bus_indexed_3", ctypes.c_double),
        ("bus_indexed_4", ctypes.c_double),
        ("apu_volts", ctypes.c_double),
        ("external_power", ctypes.c_double),
        ("external_power_1", ctypes.c_double),
        ("external_available", ctypes.c_double),
        ("external_available_1", ctypes.c_double),
        ("apu_generator", ctypes.c_double),
        ("circuit_general_panel", ctypes.c_double),
        ("circuit_avionics", ctypes.c_double),
        ("new_electrical_system", ctypes.c_double),
        ("total_load_amps", ctypes.c_double),
        ("external_connection", ctypes.c_double),
        ("external_connection_1", ctypes.c_double),
        ("external_power_volts", ctypes.c_double),
        ("external_power_volts_1", ctypes.c_double),
        # Fenix A32x — stock EXTERNAL POWER ON stays 0; use overhead / bus L-vars.
        ("fenix_ext_pwr_l", ctypes.c_double),
        ("fenix_ext_pwr_u", ctypes.c_double),
        ("fenix_apu_gen_l", ctypes.c_double),
        ("fenix_bus_ac1", ctypes.c_double),
        ("fenix_bus_ac2", ctypes.c_double),
        ("fenix_bus_ac_ess", ctypes.c_double),
        ("fenix_bus_dc1", ctypes.c_double),
        ("fenix_bus_dc2", ctypes.c_double),
        ("fenix_bus_dc_ess", ctypes.c_double),
    ]


# (struct field, SimConnect name, units) — keep order identical to TelemetryData electrical block.
ELECTRICAL_SIMVARS: tuple[tuple[str, str, str], ...] = (
    ("bus_main", "ELECTRICAL MAIN BUS VOLTAGE", "Volts"),
    ("bus_avionics", "ELECTRICAL AVIONICS BUS VOLTAGE", "Volts"),
    ("bus_battery", "ELECTRICAL BATTERY BUS VOLTAGE", "Volts"),
    ("bus_hot_battery", "ELECTRICAL HOT BATTERY BUS VOLTAGE", "Volts"),
    ("bus_genalt", "ELECTRICAL GENALT BUS VOLTAGE", "Volts"),
    ("bus_genalt_1", "ELECTRICAL GENALT BUS VOLTAGE:1", "Volts"),
    ("bus_genalt_2", "ELECTRICAL GENALT BUS VOLTAGE:2", "Volts"),
    ("bus_indexed_1", "ELECTRICAL BUS VOLTAGE:1", "Volts"),
    ("bus_indexed_2", "ELECTRICAL BUS VOLTAGE:2", "Volts"),
    ("bus_indexed_3", "ELECTRICAL BUS VOLTAGE:3", "Volts"),
    ("bus_indexed_4", "ELECTRICAL BUS VOLTAGE:4", "Volts"),
    ("apu_volts", "APU VOLTS", "Volts"),
    ("external_power", "EXTERNAL POWER ON", "Bool"),
    ("external_power_1", "EXTERNAL POWER ON:1", "Bool"),
    ("external_available", "EXTERNAL POWER AVAILABLE", "Bool"),
    ("external_available_1", "EXTERNAL POWER AVAILABLE:1", "Bool"),
    ("apu_generator", "APU GENERATOR SWITCH", "Bool"),
    ("circuit_general_panel", "CIRCUIT GENERAL PANEL ON", "Bool"),
    ("circuit_avionics", "CIRCUIT AVIONICS ON", "Bool"),
    ("new_electrical_system", "NEW ELECTRICAL SYSTEM", "Bool"),
    ("total_load_amps", "ELECTRICAL TOTAL LOAD AMPS", "Amperes"),
    ("external_connection", "EXTERNAL POWER CONNECTION ON", "Bool"),
    ("external_connection_1", "EXTERNAL POWER CONNECTION ON:1", "Bool"),
    ("external_power_volts", "ELECTRICAL EXTERNAL POWER VOLTAGE", "Volts"),
    ("external_power_volts_1", "ELECTRICAL EXTERNAL POWER VOLTAGE:1", "Volts"),
    ("fenix_ext_pwr_l", "L:I_OH_ELEC_EXT_PWR_L", "Number"),
    ("fenix_ext_pwr_u", "L:I_OH_ELEC_EXT_PWR_U", "Number"),
    ("fenix_apu_gen_l", "L:I_OH_ELEC_APU_GEN_L", "Number"),
    ("fenix_bus_ac1", "L:B_ELEC_BUS_POWER_AC1", "Number"),
    ("fenix_bus_ac2", "L:B_ELEC_BUS_POWER_AC2", "Number"),
    ("fenix_bus_ac_ess", "L:B_ELEC_BUS_POWER_AC_ESS", "Number"),
    ("fenix_bus_dc1", "L:B_ELEC_BUS_POWER_DC1", "Number"),
    ("fenix_bus_dc2", "L:B_ELEC_BUS_POWER_DC2", "Number"),
    ("fenix_bus_dc_ess", "L:B_ELEC_BUS_POWER_DC_ESS", "Number"),
)


def simobject_data_offset() -> int:
    return ctypes.sizeof(SIMCONNECT_RECV_SIMOBJECT_DATA)


def copy_telemetry_from_dispatch(buffer_addr: int) -> TelemetryData:
    """Copy telemetry out of a GetNextDispatch buffer (do not keep the pointer)."""
    src = TelemetryData.from_address(buffer_addr + simobject_data_offset())
    copied = TelemetryData()
    ctypes.memmove(ctypes.byref(copied), ctypes.byref(src), ctypes.sizeof(TelemetryData))
    return copied


def electrical_sample(t: TelemetryData) -> dict[str, float]:
    """Flat map of every electrical SimVar we query (for debug logging)."""
    out: dict[str, float] = {
        "ELECTRICAL MASTER BATTERY": round(float(t.battery_master), 3),
        "ELECTRICAL MASTER BATTERY:1": round(float(t.battery_master_1), 3),
        "ELECTRICAL MASTER BATTERY:2": round(float(t.battery_master_2), 3),
    }
    for field, simvar, _units in ELECTRICAL_SIMVARS:
        out[simvar] = round(float(getattr(t, field)), 3)
    return out


def _c_str(value: str) -> bytes:
    """SimConnect APIs take const char* (ANSI), not wchar_t*."""
    return value.encode("ascii")


class SimConnectSession:
    def __init__(self, dll_path: Path) -> None:
        self._dll_path = Path(dll_path)
        self._dll = ctypes.WinDLL(str(self._dll_path))
        self._hsim = c_void_p()
        self._open = False
        self._quit = False
        self._last = TelemetryData()
        self._have_data = False
        self.last_end_reason = ""
        self._bind()

    def _bind(self) -> None:
        # LPCSTR / const char* — not wchar (see SimConnect.h).
        self._dll.SimConnect_Open.argtypes = [
            POINTER(c_void_p),
            c_char_p,
            c_void_p,
            c_uint32,
            c_void_p,
            c_uint32,
        ]
        self._dll.SimConnect_Open.restype = c_long

        self._dll.SimConnect_Close.argtypes = [c_void_p]
        self._dll.SimConnect_Close.restype = c_long

        self._dll.SimConnect_AddToDataDefinition.argtypes = [
            c_void_p,
            c_uint32,
            c_char_p,
            c_char_p,
            c_uint32,
            c_float,
            c_uint32,
        ]
        self._dll.SimConnect_AddToDataDefinition.restype = c_long

        self._dll.SimConnect_RequestDataOnSimObject.argtypes = [
            c_void_p,
            c_uint32,
            c_uint32,
            c_uint32,
            c_uint32,
            c_uint32,
            c_uint32,
            c_uint32,
            c_uint32,
        ]
        self._dll.SimConnect_RequestDataOnSimObject.restype = c_long

        self._dll.SimConnect_GetNextDispatch.argtypes = [
            c_void_p,
            POINTER(c_void_p),
            POINTER(c_uint32),
        ]
        self._dll.SimConnect_GetNextDispatch.restype = c_long

    def __enter__(self) -> SimConnectSession:
        hr = self._dll.SimConnect_Open(
            byref(self._hsim), _c_str("ACARS Print Bridge"), None, 0, None, 0
        )
        if hr != S_OK or not self._hsim:
            raise RuntimeError(f"SimConnect_Open failed HRESULT=0x{hr & 0xFFFFFFFF:08X}")

        define_id = 1
        request_id = 1
        defs = [
            ("SIM ON GROUND", "Bool"),
            ("GROUND VELOCITY", "Knots"),
            ("PLANE ALT ABOVE GROUND", "Feet"),
            ("PLANE LATITUDE", "Degrees"),
            ("PLANE LONGITUDE", "Degrees"),
            ("ZULU YEAR", "Number"),
            ("ZULU MONTH OF YEAR", "Number"),
            ("ZULU DAY OF MONTH", "Number"),
            ("ZULU TIME", "Seconds"),
            ("ELECTRICAL MASTER BATTERY", "Bool"),
            ("ELECTRICAL MASTER BATTERY:1", "Bool"),
            ("ELECTRICAL MASTER BATTERY:2", "Bool"),
            ("EXIT OPEN:0", "Percent Over 100"),
            ("EXIT OPEN:1", "Percent Over 100"),
            ("INTERACTIVE POINT OPEN:0", "Percent Over 100"),
            ("INTERACTIVE POINT OPEN:1", "Percent Over 100"),
        ]
        defs.extend((name, units) for _field, name, units in ELECTRICAL_SIMVARS)
        for name, units in defs:
            hr = self._dll.SimConnect_AddToDataDefinition(
                self._hsim,
                define_id,
                _c_str(name),
                _c_str(units),
                SIMCONNECT_DATATYPE_FLOAT64,
                c_float(0.0),
                SIMCONNECT_UNUSED,
            )
            if hr != S_OK:
                raise RuntimeError(f"AddToDataDefinition({name}) failed")

        hr = self._dll.SimConnect_RequestDataOnSimObject(
            self._hsim,
            request_id,
            define_id,
            SIMCONNECT_OBJECT_ID_USER,
            SIMCONNECT_PERIOD_SECOND,
            0,
            0,
            0,
            0,
        )
        if hr != S_OK:
            raise RuntimeError("RequestDataOnSimObject failed")

        self._open = True
        self._quit = False
        return self

    def __exit__(self, *exc: object) -> None:
        if self._hsim:
            try:
                self._dll.SimConnect_Close(self._hsim)
            except Exception:
                pass
        self._hsim = c_void_p()
        self._open = False

    def poll(self) -> SimSnapshot | None:
        if not self._open or self._quit:
            return None

        # Pump a few dispatches each poll.
        for _ in range(32):
            p_data = c_void_p()
            cb = c_uint32()
            hr = self._dll.SimConnect_GetNextDispatch(self._hsim, byref(p_data), byref(cb))
            if hr != S_OK or not p_data:
                break
            addr = p_data.value
            if addr is None:
                break
            recv = ctypes.cast(p_data, POINTER(SIMCONNECT_RECV)).contents
            if recv.dwID == SIMCONNECT_RECV_ID_QUIT:
                self._quit = True
                self.last_end_reason = "QUIT from sim"
                log.info("SimConnect quit (sim closed or session ended)")
                return None
            if recv.dwID == SIMCONNECT_RECV_ID_EXCEPTION:
                exc = ctypes.cast(p_data, POINTER(SIMCONNECT_RECV_EXCEPTION)).contents
                name = _EXCEPTION_NAMES.get(int(exc.dwException), "UNKNOWN")
                self.last_end_reason = (
                    f"EXCEPTION {name}({exc.dwException}) "
                    f"send_id={exc.dwSendID} index={exc.dwIndex}"
                )
                log.warning(
                    "SimConnect exception=%s(%s) send_id=%s index=%s",
                    name,
                    exc.dwException,
                    exc.dwSendID,
                    exc.dwIndex,
                )
                continue
            if recv.dwID == SIMCONNECT_RECV_ID_OPEN:
                log.info("SimConnect OPEN received (protocol handshake OK)")
                continue
            if recv.dwID == SIMCONNECT_RECV_ID_SIMOBJECT_DATA:
                try:
                    self._last = copy_telemetry_from_dispatch(addr)
                    self._have_data = True
                except Exception:
                    log.exception("Failed to read SimConnect telemetry packet")
                    continue

        if not self._have_data:
            # Connected but waiting for first packet.
            return SimSnapshot(connected=True)

        t = self._last
        battery_on = (
            t.battery_master > 0.5
            or t.battery_master_1 > 0.5
            or t.battery_master_2 > 0.5
        )
        # Do NOT use EXTERNAL POWER CONNECTION ON — on Fenix that stays 1 whenever
        # a GPU is plugged at the gate, even with EXT PWR deselected / cold.
        external_power_on = (
            t.external_power > 0.5
            or t.external_power_1 > 0.5
            or t.external_power_volts >= 18.0
            or t.external_power_volts_1 >= 18.0
            # Fenix: green EXT PWR pushbutton light (stock EXTERNAL POWER ON stays 0).
            or t.fenix_ext_pwr_l > 0.5
        )
        apu_generator_on = t.apu_generator > 0.5 or t.fenix_apu_gen_l > 0.5
        main_bus_voltage = float(t.bus_main)
        door_open = (
            t.exit_open_0 > 0.15
            or t.exit_open_1 > 0.15
            or t.interactive_open_0 > 0.15
            or t.interactive_open_1 > 0.15
        )
        return SimSnapshot(
            connected=True,
            on_ground=bool(t.on_ground > 0.5),
            ground_velocity_kt=float(t.ground_velocity),
            alt_agl_ft=float(t.alt_agl),
            latitude=float(t.latitude),
            longitude=float(t.longitude),
            zulu_year=int(t.zulu_year) if t.zulu_year else None,
            zulu_month=int(t.zulu_month) if t.zulu_month else None,
            zulu_day=int(t.zulu_day) if t.zulu_day else None,
            zulu_seconds=float(t.zulu_seconds) if t.zulu_seconds is not None else None,
            battery_on=battery_on,
            external_power_on=external_power_on,
            apu_generator_on=apu_generator_on,
            main_bus_voltage=main_bus_voltage,
            main_door_open=door_open,
            electrical=electrical_sample(t),
        )


# Silence unused import warnings for types kept for clarity / future use.
_ = (c_bool, c_int)
