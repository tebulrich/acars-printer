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
    c_double,
    c_float,
    c_int,
    c_long,
    c_uint32,
    c_void_p,
    c_wchar_p,
)
from pathlib import Path

from acars_bridge.simconnect.monitor import SimSnapshot

log = logging.getLogger(__name__)

# HRESULT
S_OK = 0

# SIMCONNECT_DATATYPE
SIMCONNECT_DATATYPE_FLOAT64 = 4
SIMCONNECT_DATATYPE_INT32 = 1

# SIMCONNECT_PERIOD
SIMCONNECT_PERIOD_SECOND = 3

SIMCONNECT_OBJECT_ID_USER = 0
SIMCONNECT_UNUSED = 0xFFFFFFFF

# Recv ids
SIMCONNECT_RECV_ID_OPEN = 1
SIMCONNECT_RECV_ID_QUIT = 2
SIMCONNECT_RECV_ID_EXCEPTION = 3
SIMCONNECT_RECV_ID_SIMOBJECT_DATA = 8


class SIMCONNECT_RECV(Structure):
    _fields_ = [
        ("dwSize", c_uint32),
        ("dwVersion", c_uint32),
        ("dwID", c_uint32),
    ]


class SIMCONNECT_RECV_SIMOBJECT_DATA(Structure):
    _fields_ = [
        ("dwSize", c_uint32),
        ("dwVersion", c_uint32),
        ("dwID", c_uint32),
        ("dwRequestID", c_uint32),
        ("dwObjectType", c_uint32),
        ("dwObjectID", c_uint32),
        ("dwDefineID", c_uint32),
        ("dwFlags", c_uint32),
        ("dwentrynumber", c_uint32),
        ("dwoutof", c_uint32),
        ("dwDefineCount", c_uint32),
        # dwData follows — we read via offset into the buffer
    ]


class TelemetryData(Structure):
    _fields_ = [
        ("on_ground", c_double),
        ("ground_velocity", c_double),
        ("alt_agl", c_double),
        ("zulu_year", c_double),
        ("zulu_month", c_double),
        ("zulu_day", c_double),
        ("zulu_seconds", c_double),
    ]


class SimConnectSession:
    def __init__(self, dll_path: Path) -> None:
        self._dll_path = Path(dll_path)
        self._dll = ctypes.WinDLL(str(self._dll_path))
        self._hsim = c_void_p()
        self._open = False
        self._quit = False
        self._last = TelemetryData()
        self._have_data = False
        self._bind()

    def _bind(self) -> None:
        self._dll.SimConnect_Open.argtypes = [
            POINTER(c_void_p),
            c_wchar_p,
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
            c_wchar_p,
            c_wchar_p,
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
            byref(self._hsim), "ACARS Print Bridge", None, 0, None, 0
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
        ]
        for name, units in defs:
            hr = self._dll.SimConnect_AddToDataDefinition(
                self._hsim,
                define_id,
                name,
                units,
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
            recv = ctypes.cast(p_data, POINTER(SIMCONNECT_RECV)).contents
            if recv.dwID == SIMCONNECT_RECV_ID_QUIT:
                self._quit = True
                return None
            if recv.dwID == SIMCONNECT_RECV_ID_SIMOBJECT_DATA:
                # Layout: header then TelemetryData
                header_size = ctypes.sizeof(SIMCONNECT_RECV_SIMOBJECT_DATA)
                # GetNextDispatch gives a pointer — cast properly from p_data
                raw = ctypes.cast(p_data, POINTER(SIMCONNECT_RECV_SIMOBJECT_DATA)).contents
                data_ptr = ctypes.addressof(raw) + header_size
                telem = TelemetryData.from_address(data_ptr)
                self._last = telem
                self._have_data = True

        if not self._have_data:
            # Connected but waiting for first packet.
            return SimSnapshot(connected=True)

        t = self._last
        return SimSnapshot(
            connected=True,
            on_ground=bool(t.on_ground > 0.5),
            ground_velocity_kt=float(t.ground_velocity),
            alt_agl_ft=float(t.alt_agl),
            zulu_year=int(t.zulu_year) if t.zulu_year else None,
            zulu_month=int(t.zulu_month) if t.zulu_month else None,
            zulu_day=int(t.zulu_day) if t.zulu_day else None,
            zulu_seconds=float(t.zulu_seconds) if t.zulu_seconds is not None else None,
        )


# Silence unused import warnings for types kept for clarity / future use.
_ = (c_bool, c_int)
