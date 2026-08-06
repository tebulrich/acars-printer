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
        ("zulu_year", ctypes.c_double),
        ("zulu_month", ctypes.c_double),
        ("zulu_day", ctypes.c_double),
        ("zulu_seconds", ctypes.c_double),
        # Master battery switches — any ON counts as "a battery is on".
        ("battery_master", ctypes.c_double),
        ("battery_master_1", ctypes.c_double),
        ("battery_master_2", ctypes.c_double),
    ]


def simobject_data_offset() -> int:
    return ctypes.sizeof(SIMCONNECT_RECV_SIMOBJECT_DATA)


def copy_telemetry_from_dispatch(buffer_addr: int) -> TelemetryData:
    """Copy telemetry out of a GetNextDispatch buffer (do not keep the pointer)."""
    src = TelemetryData.from_address(buffer_addr + simobject_data_offset())
    # Field-by-field copy — dispatch memory is reused on the next poll.
    copied = TelemetryData()
    copied.on_ground = float(src.on_ground)
    copied.ground_velocity = float(src.ground_velocity)
    copied.alt_agl = float(src.alt_agl)
    copied.zulu_year = float(src.zulu_year)
    copied.zulu_month = float(src.zulu_month)
    copied.zulu_day = float(src.zulu_day)
    copied.zulu_seconds = float(src.zulu_seconds)
    copied.battery_master = float(src.battery_master)
    copied.battery_master_1 = float(src.battery_master_1)
    copied.battery_master_2 = float(src.battery_master_2)
    return copied


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
            ("ZULU YEAR", "Number"),
            ("ZULU MONTH OF YEAR", "Number"),
            ("ZULU DAY OF MONTH", "Number"),
            ("ZULU TIME", "Seconds"),
            ("ELECTRICAL MASTER BATTERY", "Bool"),
            ("ELECTRICAL MASTER BATTERY:1", "Bool"),
            ("ELECTRICAL MASTER BATTERY:2", "Bool"),
        ]
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
        return SimSnapshot(
            connected=True,
            on_ground=bool(t.on_ground > 0.5),
            ground_velocity_kt=float(t.ground_velocity),
            alt_agl_ft=float(t.alt_agl),
            zulu_year=int(t.zulu_year) if t.zulu_year else None,
            zulu_month=int(t.zulu_month) if t.zulu_month else None,
            zulu_day=int(t.zulu_day) if t.zulu_day else None,
            zulu_seconds=float(t.zulu_seconds) if t.zulu_seconds is not None else None,
            battery_on=battery_on,
        )


# Silence unused import warnings for types kept for clarity / future use.
_ = (c_bool, c_int)
