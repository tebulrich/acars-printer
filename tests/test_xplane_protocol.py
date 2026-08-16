from __future__ import annotations

import struct
from datetime import date

import pytest

from acars_bridge.services.sterile import compute_unpowered
from acars_bridge.simconnect.monitor import aircraft_is_powered
from acars_bridge.xplane.protocol import (
    RREF_HEADER,
    calendar_from_year_and_doy,
    doors_from_values,
    kinematics_to_snapshot,
    normalize_xplane_host,
    normalize_xplane_port,
    pack_rref_subscribe,
    parse_becn,
    parse_rref_values,
    unpack_rref_subscribe,
)


def test_pack_rref_subscribe_layout():
    packet = pack_rref_subscribe(
        index=3, dataref="sim/flightmodel/position/latitude", hz=2
    )
    assert packet.startswith(RREF_HEADER)
    assert len(packet) == 5 + 4 + 4 + 400
    freq, index, name = unpack_rref_subscribe(packet)
    assert freq == 2
    assert index == 3
    assert name == "sim/flightmodel/position/latitude"


def test_parse_rref_values_multiple():
    payload = RREF_HEADER + struct.pack("<ifif", 1, 47.45, 2, -122.3)
    values = parse_rref_values(payload)
    assert values[1] == pytest.approx(47.45)
    assert values[2] == pytest.approx(-122.3)


def test_parse_becn_version_and_port():
    body = struct.pack("<BBiiIH", 1, 2, 1, 121400, 1, 49000)
    parsed = parse_becn(b"BECN\x00" + body)
    assert parsed is not None
    assert parsed.version_number == 121400
    assert parsed.port == 49000
    assert parsed.xplane_major == 12


def test_parse_becn_rejects_junk():
    assert parse_becn(b"") is None
    assert parse_becn(b"DATA\x00") is None


def test_calendar_from_year_and_doy():
    year, month, day = calendar_from_year_and_doy(2026, 0)
    assert (year, month, day) == (2026, 1, 1)
    year, month, day = calendar_from_year_and_doy(2026, 227)
    assert date(year, month, day) == date(2026, 8, 16)


def test_kinematics_to_snapshot_converts_units():
    snap = kinematics_to_snapshot(
        {
            "latitude": 47.45,
            "longitude": -122.3,
            "y_agl_m": 30.48,
            "groundspeed_mps": 51.44,
            "onground": 0.0,
            "zulu_seconds": 3661.0,
            "date_days": 227.0,
            "year": 2026.0,
        },
        detail="X-Plane 12",
    )
    assert snap.connected is True
    assert snap.source == "xplane"
    assert snap.latitude == 47.45
    assert snap.on_ground is False
    assert abs(snap.alt_agl_ft - 100.0) < 0.2
    assert abs(snap.ground_velocity_kt - 100.0) < 0.2
    assert snap.zulu_year == 2026
    assert snap.zulu_month == 8
    assert snap.zulu_day == 16
    assert snap.zulu_seconds == 3661.0
    assert snap.electrical is None
    assert snap.main_door_open is None
    assert aircraft_is_powered(snap) is None
    assert compute_unpowered(snap, require_powered=True) is False


def test_kinematics_stock_buses_powered_and_doors_closed():
    snap = kinematics_to_snapshot(
        {
            "latitude": 47.45,
            "longitude": -122.3,
            "y_agl_m": 0.0,
            "groundspeed_mps": 0.0,
            "onground": 1.0,
            "bus_volts_0": 28.0,
            "bus_volts_1": 28.75,
            "bus_volts_2": 28.05,
            "generator_on_0": 1.0,
            "generator_on_1": 1.0,
            "avionics_on": 1.0,
            "apu_generator_on": 0.0,
            "door_ratio_0": 0.0,
            "door_ratio_1": 0.0,
            "door_ratio_2": 0.0,
            "door_ratio_3": 0.0,
        }
    )
    assert snap.main_bus_voltage == pytest.approx(28.75)
    assert snap.electrical is not None
    assert snap.electrical["ELECTRICAL BUS VOLTAGE:1"] == 28.0
    assert snap.main_door_open is False
    assert snap.apu_generator_on is False
    assert snap.electrical["XP GENERATOR ON:1"] == 1.0
    assert aircraft_is_powered(snap) is True
    assert compute_unpowered(snap, require_powered=True) is False


def test_kinematics_dummy_buses_without_a_source_are_off():
    """Laminar buses at 28 V while engines / APU / GPU are sampled off = cold."""
    snap = kinematics_to_snapshot(
        {
            "bus_volts_0": 28.0,
            "bus_volts_1": 28.0,
            "bus_volts_2": 28.0,
            "generator_on_0": 0.0,
            "generator_on_1": 0.0,
            "avionics_on": 1.0,
            "apu_generator_on": 0.0,
            "gpu_generator_on": 0.0,
            "gpu_on": 0.0,
            "gpu_generator_volts": 0.0,
        }
    )
    assert snap.main_bus_voltage == 28.0
    assert snap.external_power_on is False
    assert aircraft_is_powered(snap) is False
    assert compute_unpowered(snap, require_powered=True) is True


def test_kinematics_ground_power_relay_is_powered():
    snap = kinematics_to_snapshot(
        {
            "bus_volts_0": 28.0,
            "generator_on_0": 0.0,
            "generator_on_1": 0.0,
            "apu_generator_on": 0.0,
            "gpu_generator_on": 1.0,
            "gpu_generator_volts": 28.0,
        }
    )
    assert snap.external_power_on is True
    assert aircraft_is_powered(snap) is True
    assert compute_unpowered(snap, require_powered=True) is False


def test_kinematics_legacy_gpu_on_counts_as_ground_power():
    snap = kinematics_to_snapshot({"gpu_on": 1.0, "generator_on_0": 0.0})
    assert snap.external_power_on is True
    assert aircraft_is_powered(snap) is True


def test_kinematics_gpu_plugged_but_not_selected_is_not_powered():
    """Volts mean the cart is plugged in — not that EXT PWR is on."""
    snap = kinematics_to_snapshot(
        {
            "bus_volts_0": 28.0,
            "generator_on_0": 0.0,
            "apu_generator_on": 0.0,
            "gpu_generator_on": 0.0,
            "gpu_on": 0.0,
            "gpu_generator_volts": 28.0,
        }
    )
    assert snap.external_power_on is False
    assert aircraft_is_powered(snap) is False
    assert compute_unpowered(snap, require_powered=True) is True


def test_kinematics_stock_sources_off_are_unpowered():
    """737 / A330 cold-and-dark: every source sampled off → PWR off, hold prints."""
    snap = kinematics_to_snapshot(
        {
            "bus_volts_0": 0.0,
            "bus_volts_1": 0.0,
            "bus_volts_2": 0.0,
            "avionics_on": 0.0,
            "generator_on_0": 0.0,
            "apu_generator_on": 0.0,
            "apu_running": 0.0,
            "apu_n1": 0.0,
            "eng_running_0": 0.0,
            "eng_n1_0": 0.0,
            "door_ratio_0": 0.8,
        }
    )
    assert snap.main_bus_voltage == 0.0
    assert aircraft_is_powered(snap) is False
    assert compute_unpowered(snap, require_powered=True) is True
    assert snap.main_door_open is True


def test_kinematics_apu_running_is_powered_even_if_buses_are_dark():
    snap = kinematics_to_snapshot(
        {
            "bus_volts_0": 0.0,
            "generator_on_0": 0.0,
            "apu_generator_on": 0.0,
            "apu_running": 1.0,
            "apu_n1": 100.0,
        }
    )
    assert aircraft_is_powered(snap) is True
    assert compute_unpowered(snap, require_powered=True) is False


def test_kinematics_engine_running_is_powered_even_if_buses_are_dark():
    snap = kinematics_to_snapshot(
        {
            "bus_volts_0": 0.0,
            "generator_on_0": 0.0,
            "apu_running": 0.0,
            "eng_running_0": 1.0,
            "eng_n1_0": 22.0,
        }
    )
    assert aircraft_is_powered(snap) is True
    assert compute_unpowered(snap, require_powered=True) is False


def test_kinematics_engine_n1_alone_is_powered():
    snap = kinematics_to_snapshot(
        {
            "bus_volts_0": 0.0,
            "eng_running_0": 0.0,
            "eng_n1_0": 18.0,
        }
    )
    assert aircraft_is_powered(snap) is True


def test_kinematics_toliss_apu_avail_is_powered():
    snap = kinematics_to_snapshot(
        {
            "bus_volts_0": 28.0,
            "generator_on_0": 0.0,
            "apu_running": 0.0,
            "toliss_apu_avail": 1.0,
        }
    )
    assert aircraft_is_powered(snap) is True
    assert compute_unpowered(snap, require_powered=True) is False


def test_kinematics_buses_only_remain_unknown():
    snap = kinematics_to_snapshot({"bus_volts_0": 28.0, "avionics_on": 1.0})
    assert aircraft_is_powered(snap) is None
    assert compute_unpowered(snap, require_powered=True) is False


def test_kinematics_apu_n1_counts_as_running():
    snap = kinematics_to_snapshot(
        {
            "bus_volts_0": 0.0,
            "apu_generator_on": 0.0,
            "apu_n1": 95.0,
        }
    )
    assert aircraft_is_powered(snap) is True


def test_doors_from_values_ratio_and_switch():
    assert doors_from_values({}) is None
    assert doors_from_values({"door_ratio_0": 0.0}) is False
    assert doors_from_values({"door_ratio_1": 0.2}) is True
    assert doors_from_values({"door_switch_0": 1.0}) is True
    assert doors_from_values({"door_switch_1": 0.0, "door_ratio_0": 0.1}) is False


def test_normalize_xplane_host_and_port():
    assert normalize_xplane_host("") == "auto"
    assert normalize_xplane_host("  AUTO ") == "auto"
    assert normalize_xplane_host("10.0.0.8") == "10.0.0.8"
    assert normalize_xplane_port("49000") == 49000
    assert normalize_xplane_port("nope") == 49000
    assert normalize_xplane_port(0) == 49000
    assert normalize_xplane_port(70000) == 49000
    assert normalize_xplane_port(49010) == 49010
