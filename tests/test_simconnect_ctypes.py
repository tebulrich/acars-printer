from __future__ import annotations

import ctypes

from acars_bridge.simconnect._ctypes_client import (
    SIMCONNECT_RECV_SIMOBJECT_DATA,
    TelemetryData,
    copy_telemetry_from_dispatch,
    simobject_data_offset,
)


def test_simobject_payload_offset_matches_header_size():
    assert simobject_data_offset() == ctypes.sizeof(SIMCONNECT_RECV_SIMOBJECT_DATA)


def test_copy_telemetry_from_dispatch_reads_after_header():
    header = SIMCONNECT_RECV_SIMOBJECT_DATA()
    header.dwSize = ctypes.sizeof(SIMCONNECT_RECV_SIMOBJECT_DATA) + ctypes.sizeof(TelemetryData)
    header.dwID = 8
    header.dwDefineCount = 10

    payload = TelemetryData()
    payload.on_ground = 1.0
    payload.ground_velocity = 12.5
    payload.alt_agl = 34.0
    payload.zulu_year = 2026.0
    payload.zulu_month = 8.0
    payload.zulu_day = 6.0
    payload.zulu_seconds = 3600.0
    payload.battery_master = 1.0
    payload.battery_master_1 = 0.0
    payload.battery_master_2 = 0.0

    blob = ctypes.create_string_buffer(
        ctypes.sizeof(SIMCONNECT_RECV_SIMOBJECT_DATA) + ctypes.sizeof(TelemetryData)
    )
    ctypes.memmove(blob, ctypes.byref(header), ctypes.sizeof(header))
    ctypes.memmove(
        ctypes.addressof(blob) + simobject_data_offset(),
        ctypes.byref(payload),
        ctypes.sizeof(payload),
    )

    copied = copy_telemetry_from_dispatch(ctypes.addressof(blob))
    assert copied.on_ground == 1.0
    assert copied.ground_velocity == 12.5
    assert copied.alt_agl == 34.0
    assert copied.zulu_year == 2026.0
    assert copied.zulu_seconds == 3600.0
    assert copied.battery_master == 1.0
