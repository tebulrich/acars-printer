"""Live checks against a running X-Plane 11/12. Skipped when the sim is off."""

from __future__ import annotations

import time

import pytest

from acars_bridge.services.sterile import compute_sterile, compute_unpowered
from acars_bridge.simconnect.monitor import aircraft_is_powered
from acars_bridge.xplane.detect import detect_running_sims
from acars_bridge.xplane.monitor import XPlaneUdpMonitor


def _running_xplane():
    return next((s for s in detect_running_sims() if s.kind == "xplane"), None)


pytestmark = pytest.mark.skipif(
    _running_xplane() is None, reason="X-Plane is not running"
)


def test_live_xplane_process_is_classified():
    xp = _running_xplane()
    assert xp is not None
    assert "x-plane" in xp.exe_name.lower() or "xplane" in xp.exe_name.lower()


def test_live_xplane_rref_snapshot_and_gates():
    mon = XPlaneUdpMonitor(
        host="127.0.0.1",
        port=49000,
        stale_seconds=3.0,
        subscribe_interval=0.4,
    )
    mon.start()
    snap = None
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            snap = mon.snapshot()
            if snap is not None and snap.connected:
                break
            time.sleep(0.1)
    finally:
        mon.stop()

    assert snap is not None and snap.connected
    assert snap.source == "xplane"
    assert snap.latitude is not None
    assert snap.longitude is not None
    assert -90.0 <= snap.latitude <= 90.0
    assert -180.0 <= snap.longitude <= 180.0
    assert snap.zulu_seconds is not None
    # Sterile must be a real bool from kinematics — not stuck unknown.
    assert compute_sterile(snap) in {True, False}
    if snap.electrical is not None:
        powered = aircraft_is_powered(snap)
        assert powered in {True, False, None}
        if powered is True:
            assert compute_unpowered(snap, require_powered=True) is False
        elif powered is False:
            assert compute_unpowered(snap, require_powered=True) is True
        else:
            assert compute_unpowered(snap, require_powered=True) is False
        assert snap.main_door_open is None or isinstance(snap.main_door_open, bool)
    else:
        assert compute_unpowered(snap, require_powered=True) is False
