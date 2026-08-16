from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from acars_bridge.simconnect.monitor import SimSnapshot
from acars_bridge.xplane.detect import xplane_major_from_version

RREF_HEADER = b"RREF\x00"
BECN_HEADER = b"BECN\x00"
DREF_NAME_BYTES = 400

# Stock Laminar datarefs (XP11/12), plus ToLiss APUAvail as a source-live hint.
# Do not subscribe inverted annunciators (e.g. Zibo apu_gen_off_bus).
DATAREFS: dict[str, str] = {
    "latitude": "sim/flightmodel/position/latitude",
    "longitude": "sim/flightmodel/position/longitude",
    "y_agl_m": "sim/flightmodel/position/y_agl",
    "groundspeed_mps": "sim/flightmodel/position/groundspeed",
    "onground": "sim/flightmodel/failures/onground_any",
    "zulu_seconds": "sim/time/zulu_time_sec",
    "date_days": "sim/time/local_date_days",
    "year": "sim/cockpit2/clock_timer/current_year",
    "bus_volts_0": "sim/cockpit2/electrical/bus_volts[0]",
    "bus_volts_1": "sim/cockpit2/electrical/bus_volts[1]",
    "bus_volts_2": "sim/cockpit2/electrical/bus_volts[2]",
    "generator_on_0": "sim/cockpit2/electrical/generator_on[0]",
    "generator_on_1": "sim/cockpit2/electrical/generator_on[1]",
    "apu_generator_on": "sim/cockpit2/electrical/APU_generator_on",
    "apu_running": "sim/cockpit2/electrical/APU_running",
    "apu_n1": "sim/cockpit2/electrical/APU_N1_percent",
    "apu_running_legacy": "sim/cockpit/engine/APU_running",
    "apu_gen_legacy": "sim/cockpit/electrical/generator_apu_on",
    "gpu_generator_on": "sim/cockpit2/electrical/GPU_generator_on",
    "gpu_generator_volts": "sim/cockpit2/electrical/GPU_generator_volts",
    "gpu_on": "sim/cockpit/electrical/gpu_on",
    "eng_running_0": "sim/flightmodel/engine/ENGN_running[0]",
    "eng_running_1": "sim/flightmodel/engine/ENGN_running[1]",
    "eng_running_2": "sim/flightmodel/engine/ENGN_running[2]",
    "eng_running_3": "sim/flightmodel/engine/ENGN_running[3]",
    "eng_n1_0": "sim/cockpit2/engine/indicators/N1_percent[0]",
    "eng_n1_1": "sim/cockpit2/engine/indicators/N1_percent[1]",
    "eng_n1_2": "sim/cockpit2/engine/indicators/N1_percent[2]",
    "eng_n1_3": "sim/cockpit2/engine/indicators/N1_percent[3]",
    "toliss_apu_avail": "AirbusFBW/APUAvail",
    "avionics_on": "sim/cockpit2/switches/avionics_power_on",
    "door_ratio_0": "sim/flightmodel2/misc/door_open_ratio[0]",
    "door_ratio_1": "sim/flightmodel2/misc/door_open_ratio[1]",
    "door_ratio_2": "sim/flightmodel2/misc/door_open_ratio[2]",
    "door_ratio_3": "sim/flightmodel2/misc/door_open_ratio[3]",
    "door_switch_0": "sim/cockpit2/switches/door_open[0]",
    "door_switch_1": "sim/cockpit2/switches/door_open[1]",
}

RREF_INDEX: dict[str, int] = {
    name: index for index, name in enumerate(DATAREFS, start=1)
}
INDEX_TO_KEY: dict[int, str] = {index: name for name, index in RREF_INDEX.items()}

METERS_TO_FEET = 3.280839895
MPS_TO_KT = 1.943844492
DOOR_OPEN_RATIO = 0.15
_BUS_KEYS = ("bus_volts_0", "bus_volts_1", "bus_volts_2")
_DOOR_RATIO_KEYS = ("door_ratio_0", "door_ratio_1", "door_ratio_2", "door_ratio_3")
_DOOR_SWITCH_KEYS = ("door_switch_0", "door_switch_1")
_GPU_ON_KEYS = ("gpu_generator_on", "gpu_on")
APU_N1_RUNNING = 50.0
ENGINE_N1_RUNNING = 15.0
_VALUE_TO_ELEC: dict[str, str] = {
    "generator_on_0": "XP GENERATOR ON:1",
    "generator_on_1": "XP GENERATOR ON:2",
    "apu_generator_on": "APU GENERATOR SWITCH",
    "apu_running": "XP APU RUNNING",
    "apu_running_legacy": "XP APU RUNNING LEGACY",
    "apu_n1": "XP APU N1",
    "apu_gen_legacy": "XP APU GEN LEGACY",
    "gpu_generator_on": "XP GPU ON",
    "gpu_on": "XP GPU ON LEGACY",
    "gpu_generator_volts": "XP GPU VOLTS",
    "eng_running_0": "XP ENG RUNNING:1",
    "eng_running_1": "XP ENG RUNNING:2",
    "eng_running_2": "XP ENG RUNNING:3",
    "eng_running_3": "XP ENG RUNNING:4",
    "eng_n1_0": "XP ENG N1:1",
    "eng_n1_1": "XP ENG N1:2",
    "eng_n1_2": "XP ENG N1:3",
    "eng_n1_3": "XP ENG N1:4",
    "toliss_apu_avail": "XP TOLISS APU AVAIL",
    "avionics_on": "XP AVIONICS ON",
}
_ELEC_KEYS = _BUS_KEYS + tuple(_VALUE_TO_ELEC)
_SOURCE_ON_KEYS = (
    "XP GENERATOR ON:1",
    "XP GENERATOR ON:2",
    "APU GENERATOR SWITCH",
    "XP APU RUNNING",
    "XP APU RUNNING LEGACY",
    "XP APU GEN LEGACY",
    "XP GPU ON",
    "XP GPU ON LEGACY",
    "XP ENG RUNNING:1",
    "XP ENG RUNNING:2",
    "XP ENG RUNNING:3",
    "XP ENG RUNNING:4",
    "XP TOLISS APU AVAIL",
)
_SOURCE_N1_KEYS = ("XP APU N1", "XP ENG N1:1", "XP ENG N1:2", "XP ENG N1:3", "XP ENG N1:4")


@dataclass(frozen=True, slots=True)
class XPlaneBeacon:
    version_number: int
    port: int
    xplane_major: int | None
    host_id: int = 1


def pack_rref_subscribe(*, index: int, dataref: str, hz: int = 2) -> bytes:
    name = dataref.encode("ascii", errors="replace")[: DREF_NAME_BYTES - 1]
    padded = name + b"\x00" * (DREF_NAME_BYTES - len(name))
    return RREF_HEADER + struct.pack("<ii", int(hz), int(index)) + padded


def unpack_rref_subscribe(packet: bytes) -> tuple[int, int, str]:
    if not packet.startswith(RREF_HEADER) or len(packet) < 13:
        raise ValueError("not an RREF subscribe packet")
    freq, index = struct.unpack_from("<ii", packet, 5)
    raw = packet[13 : 13 + DREF_NAME_BYTES]
    name = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")
    return int(freq), int(index), name


def parse_rref_values(packet: bytes) -> dict[int, float]:
    if not packet.startswith(b"RREF") or len(packet) < 5:
        return {}
    payload = packet[5:]
    values: dict[int, float] = {}
    offset = 0
    while offset + 8 <= len(payload):
        index, value = struct.unpack_from("<if", payload, offset)
        values[int(index)] = float(value)
        offset += 8
    return values


def parse_becn(packet: bytes) -> XPlaneBeacon | None:
    if not packet.startswith(BECN_HEADER) or len(packet) < 5 + 16:
        return None
    try:
        major, minor, host_id, version, role, port = struct.unpack_from(
            "<BBiiIH", packet, 5
        )
    except struct.error:
        return None
    del major, minor, role
    version_i = int(version)
    return XPlaneBeacon(
        version_number=version_i,
        port=int(port),
        xplane_major=xplane_major_from_version(version_i),
        host_id=int(host_id),
    )


def calendar_from_year_and_doy(year: int, days_since_jan1: int) -> tuple[int, int, int]:
    """X-Plane ``local_date_days`` is 0 = 1 January."""
    day = date(int(year), 1, 1) + timedelta(days=int(days_since_jan1))
    return day.year, day.month, day.day


def electrical_from_values(values: dict[str, float]) -> dict[str, float] | None:
    """Map stock XP electrical datarefs. Do not alias avionics onto MSFS panel keys.

    Study-level aircraft (ToLiss A330, …) often leave Laminar bus volts stuck
    at 28 V or 0 V. Only engine / APU / GPU *source* flags are treated as
    “powered” later — not GPU volts and not bus volts.
    """
    if not any(key in values for key in _ELEC_KEYS):
        return None
    out: dict[str, float] = {}
    for index, key in enumerate(_BUS_KEYS, start=1):
        if key in values:
            out[f"ELECTRICAL BUS VOLTAGE:{index}"] = float(values[key])
    for src, dest in _VALUE_TO_ELEC.items():
        if src in values:
            out[dest] = float(values[src])
    return out


def electrical_sources_live(elec: dict[str, float] | None) -> bool | None:
    """True if an engine, APU, or GPU source is live; False if those were sampled off.

    ``None`` when no source keys were sampled. Bus volts and avionics are ignored.
    """
    if not elec:
        return None
    saw_source = False
    for key in _SOURCE_ON_KEYS:
        if key not in elec:
            continue
        saw_source = True
        try:
            if float(elec[key]) >= 0.5:
                return True
        except (TypeError, ValueError):
            pass
    for key in _SOURCE_N1_KEYS:
        if key not in elec:
            continue
        saw_source = True
        threshold = APU_N1_RUNNING if key == "XP APU N1" else ENGINE_N1_RUNNING
        try:
            if float(elec[key]) >= threshold:
                return True
        except (TypeError, ValueError):
            pass
    if saw_source:
        return False
    return None


def gpu_selected_from_values(values: dict[str, float]) -> bool | None:
    """True when the GPU relay is closed. Plugged-in volts alone do not count."""
    present = [key for key in _GPU_ON_KEYS if key in values]
    if not present:
        return None
    return any(float(values[key]) >= 0.5 for key in present)


def main_bus_from_values(values: dict[str, float]) -> float | None:
    present = [float(values[key]) for key in _BUS_KEYS if key in values]
    return max(present) if present else None


def doors_from_values(values: dict[str, float]) -> bool | None:
    if not any(key in values for key in _DOOR_RATIO_KEYS + _DOOR_SWITCH_KEYS):
        return None
    for key in _DOOR_RATIO_KEYS:
        if key in values and float(values[key]) > DOOR_OPEN_RATIO:
            return True
    for key in _DOOR_SWITCH_KEYS:
        if key in values and float(values[key]) >= 0.5:
            return True
    return False


def normalize_xplane_host(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw or raw.lower() == "auto":
        return "auto"
    return raw


def normalize_xplane_port(value: object) -> int:
    try:
        port = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 49000
    if port < 1 or port > 65535:
        return 49000
    return port


def values_by_key(indexed: dict[int, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for index, value in indexed.items():
        key = INDEX_TO_KEY.get(int(index))
        if key:
            out[key] = float(value)
    return out


def kinematics_to_snapshot(
    values: dict[str, float],
    *,
    detail: str = "X-Plane",
) -> SimSnapshot:
    lat = values.get("latitude")
    lon = values.get("longitude")
    agl_m = values.get("y_agl_m")
    gs_mps = values.get("groundspeed_mps")
    onground = values.get("onground")
    zulu_seconds = values.get("zulu_seconds")
    date_days = values.get("date_days")
    year_raw = values.get("year")

    year = int(year_raw) if year_raw and year_raw >= 1970 else datetime.now(UTC).year
    zulu_year = zulu_month = zulu_day = None
    if date_days is not None:
        try:
            zulu_year, zulu_month, zulu_day = calendar_from_year_and_doy(
                year, int(date_days)
            )
        except ValueError:
            zulu_year = zulu_month = zulu_day = None

    electrical = electrical_from_values(values)
    bus = main_bus_from_values(values)
    return SimSnapshot(
        connected=True,
        source="xplane",
        on_ground=bool(onground is not None and onground >= 0.5),
        ground_velocity_kt=(float(gs_mps) * MPS_TO_KT) if gs_mps is not None else 0.0,
        alt_agl_ft=(float(agl_m) * METERS_TO_FEET) if agl_m is not None else 0.0,
        latitude=float(lat) if lat is not None else None,
        longitude=float(lon) if lon is not None else None,
        zulu_year=zulu_year,
        zulu_month=zulu_month,
        zulu_day=zulu_day,
        zulu_seconds=float(zulu_seconds) if zulu_seconds is not None else None,
        main_bus_voltage=bus,
        electrical=electrical,
        main_door_open=doors_from_values(values),
        external_power_on=gpu_selected_from_values(values),
        apu_generator_on=(
            bool(values["apu_generator_on"] >= 0.5)
            if "apu_generator_on" in values
            else None
        ),
        detail=detail,
    )
