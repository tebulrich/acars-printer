from __future__ import annotations

from acars_bridge.xplane.detect import (
    RunningSim,
    classify_sim_executable,
    detect_running_sims,
    preferred_sim,
    xplane_major_from_version,
)


def test_classify_msfs_and_2024():
    assert classify_sim_executable("FlightSimulator.exe") == RunningSim(
        kind="msfs", exe_name="FlightSimulator.exe"
    )
    assert classify_sim_executable("FlightSimulator2024.exe") == RunningSim(
        kind="msfs", exe_name="FlightSimulator2024.exe"
    )


def test_classify_xplane_from_basename_and_path():
    xp = classify_sim_executable("X-Plane.exe")
    assert xp is not None
    assert xp.kind == "xplane"
    assert xp.xplane_major is None

    xp11 = classify_sim_executable(
        "X-Plane.exe",
        r"C:\X-Plane 11\X-Plane.exe",
    )
    assert xp11 is not None
    assert xp11.xplane_major == 11

    xp12 = classify_sim_executable(
        "X-Plane.exe",
        r"D:\Steam\steamapps\common\X-Plane 12\X-Plane.exe",
    )
    assert xp12 is not None
    assert xp12.xplane_major == 12


def test_classify_ignores_unrelated():
    assert classify_sim_executable("notepad.exe") is None
    assert classify_sim_executable("SayIntentionsAI.exe") is None
    assert classify_sim_executable("acars-print-bridge.exe") is None


def test_detect_running_sims_from_injected_list():
    found = detect_running_sims(
        [
            ("chrome.exe", r"C:\Chrome\chrome.exe"),
            ("X-Plane.exe", r"C:\X-Plane 12\X-Plane.exe"),
            ("FlightSimulator.exe", r"C:\MSFS\FlightSimulator.exe"),
        ]
    )
    kinds = {s.kind for s in found}
    assert kinds == {"msfs", "xplane"}
    xp = next(s for s in found if s.kind == "xplane")
    assert xp.xplane_major == 12


def test_preferred_sim_msfs_wins_when_both():
    sims = [
        RunningSim(kind="xplane", exe_name="X-Plane.exe", xplane_major=12),
        RunningSim(kind="msfs", exe_name="FlightSimulator.exe"),
    ]
    pref = preferred_sim(sims)
    assert pref is not None
    assert pref.kind == "msfs"


def test_preferred_sim_xplane_when_only_xp():
    sims = [RunningSim(kind="xplane", exe_name="X-Plane.exe", xplane_major=12)]
    pref = preferred_sim(sims)
    assert pref is not None
    assert pref.kind == "xplane"


def test_xplane_major_from_beacon_version():
    assert xplane_major_from_version(121400) == 12
    assert xplane_major_from_version(120014) == 12
    assert xplane_major_from_version(115501) == 11
    assert xplane_major_from_version(105000) is None
    assert xplane_major_from_version(None) is None
