"""MSFS menu / world-hub must not count as electrically powered."""

from __future__ import annotations

from acars_bridge.services.sterile import compute_sterile
from acars_bridge.simconnect._ctypes_client import application_is_msfs_2024
from acars_bridge.simconnect.monitor import (
    SimSnapshot,
    aircraft_is_powered,
    camera_state_is_menu,
    flight_path_is_menu,
    resolve_in_session,
)


def _live_electrical() -> dict[str, float]:
    """Typical hangar / leftover SimVars that look 'powered' in the MSFS menu."""
    return {
        "CIRCUIT GENERAL PANEL ON": 1.0,
        "CIRCUIT AVIONICS ON": 1.0,
        "ELECTRICAL MAIN BUS VOLTAGE": 28.0,
        "ELECTRICAL AVIONICS BUS VOLTAGE": 28.0,
        "ELECTRICAL BUS VOLTAGE:1": 28.0,
        "EXTERNAL POWER ON": 0.0,
        "NEW ELECTRICAL SYSTEM": 0.0,
    }


def test_menu_flight_files_are_detected() -> None:
    assert flight_path_is_menu(r"C:\MSFS\flights\MainMenu.FLT") is True
    assert flight_path_is_menu("MAINMENU.flt") is True
    assert flight_path_is_menu("ONBOARD.FLT") is True
    assert flight_path_is_menu(r"C:\MSFS\flights\customflight.FLT") is False
    assert flight_path_is_menu("") is False


def test_camera_state_menu_shared_and_2024_hub() -> None:
    # Shared hangar / world-map / menu RTC numbers (2020 + 2024).
    assert camera_state_is_menu(12.0) is True
    assert camera_state_is_menu(13.0) is True
    # 2024 Idle / World Map Idle — main menu and hub.
    assert camera_state_is_menu(29.0) is True
    assert camera_state_is_menu(30.0) is True
    # Cockpit is a real flight view.
    assert camera_state_is_menu(2.0) is False
    # 2024 World Map (10) only when we know it is 2024 (10 is drone in 2020).
    assert camera_state_is_menu(10.0, msfs_2024=False) is False
    assert camera_state_is_menu(10.0, msfs_2024=True) is True


def test_application_is_msfs_2024() -> None:
    assert application_is_msfs_2024("SunRise", 12) is True
    assert application_is_msfs_2024("Microsoft Flight Simulator 2024", 1) is True
    assert application_is_msfs_2024("KittyHawk", 11) is False


def test_resolve_in_session_menu_beats_sim_running() -> None:
    assert (
        resolve_in_session(sim_running=True, flight_path="MainMenu.FLT") is False
    )
    assert resolve_in_session(sim_running=True, camera_state=29.0) is False
    assert resolve_in_session(sim_running=True, camera_state=2.0) is True
    assert resolve_in_session(sim_running=False, camera_state=2.0) is False
    assert resolve_in_session(sim_running=None, camera_state=2.0) is None


def test_msfs_menu_leftover_buses_are_not_powered() -> None:
    snap = SimSnapshot(
        connected=True,
        source="simconnect",
        in_session=False,
        main_bus_voltage=28.0,
        external_power_on=False,
        electrical=_live_electrical(),
    )
    assert aircraft_is_powered(snap) is None


def test_msfs_unknown_session_does_not_trust_electrical() -> None:
    snap = SimSnapshot(
        connected=True,
        source="simconnect",
        in_session=None,
        main_bus_voltage=28.0,
        electrical=_live_electrical(),
    )
    assert aircraft_is_powered(snap) is None


def test_msfs_in_flight_still_uses_electrical() -> None:
    snap = SimSnapshot(
        connected=True,
        source="simconnect",
        in_session=True,
        main_bus_voltage=28.0,
        electrical=_live_electrical(),
    )
    assert aircraft_is_powered(snap) is True


def test_sterile_ignores_menu_leftover_airborne_sample() -> None:
    snap = SimSnapshot(
        connected=True,
        source="simconnect",
        in_session=False,
        on_ground=False,
        ground_velocity_kt=200,
        alt_agl_ft=400,
    )
    assert compute_sterile(snap) is False
