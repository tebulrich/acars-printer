from __future__ import annotations

import socket
import struct
import threading
import time

import pytest

from acars_bridge.services.sterile import compute_sterile, compute_unpowered
from acars_bridge.simconnect.monitor import (
    CompositeSimMonitor,
    SimSnapshot,
    aircraft_is_powered,
)
from acars_bridge.xplane.detect import RunningSim
from acars_bridge.xplane.monitor import XPlaneUdpMonitor
from acars_bridge.xplane.protocol import RREF_HEADER, RREF_INDEX


class _FakeSim:
    def __init__(self, snap: SimSnapshot | None) -> None:
        self._snap = snap

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def snapshot(self) -> SimSnapshot | None:
        return self._snap


def _serve_one_rref(server: socket.socket, values: dict[int, float]) -> None:
    try:
        server.settimeout(2.0)
        data, addr = server.recvfrom(2048)
        if data.startswith(RREF_HEADER):
            payload = RREF_HEADER
            for idx, val in values.items():
                payload += struct.pack("<if", idx, float(val))
            server.sendto(payload, addr)
    except OSError:
        return


def test_xplane_monitor_reads_rref_from_fake_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    values = {
        RREF_INDEX["latitude"]: 47.45,
        RREF_INDEX["longitude"]: -122.3,
        RREF_INDEX["y_agl_m"]: 30.48,
        RREF_INDEX["groundspeed_mps"]: 51.44,
        RREF_INDEX["onground"]: 0.0,
        RREF_INDEX["zulu_seconds"]: 3661.0,
        RREF_INDEX["date_days"]: 227.0,
        RREF_INDEX["year"]: 2026.0,
    }
    thread = threading.Thread(target=_serve_one_rref, args=(server, values), daemon=True)
    thread.start()

    mon = XPlaneUdpMonitor(
        host="127.0.0.1",
        port=port,
        stale_seconds=2.0,
        subscribe_interval=0.15,
        detect_fn=lambda: [
            RunningSim(kind="xplane", exe_name="X-Plane.exe", xplane_major=12)
        ],
    )
    mon.start()
    snap = None
    deadline = time.monotonic() + 3.0
    try:
        while time.monotonic() < deadline:
            snap = mon.snapshot()
            if snap is not None and snap.connected:
                break
            time.sleep(0.05)
    finally:
        mon.stop()
        server.close()
        thread.join(timeout=1.0)

    assert snap is not None and snap.connected
    assert snap.source == "xplane"
    assert snap.latitude == pytest.approx(47.45, rel=1e-4)
    assert snap.on_ground is False
    assert snap.alt_agl_ft == pytest.approx(100.0, abs=0.3)
    assert "X-Plane" in (snap.detail or "")


def test_composite_prefers_msfs_when_both_connected():
    msfs = _FakeSim(
        SimSnapshot(connected=True, source="simconnect", latitude=1.0, detail="msfs")
    )
    xp = _FakeSim(
        SimSnapshot(connected=True, source="xplane", latitude=2.0, detail="xp")
    )
    combo = CompositeSimMonitor(msfs, xp)
    snap = combo.snapshot()
    assert snap is not None
    assert snap.source == "simconnect"
    assert snap.latitude == 1.0


def test_composite_uses_xplane_when_msfs_down():
    msfs = _FakeSim(SimSnapshot(connected=False, detail="no msfs"))
    xp = _FakeSim(
        SimSnapshot(connected=True, source="xplane", latitude=47.4, detail="X-Plane 12")
    )
    combo = CompositeSimMonitor(msfs, xp)
    snap = combo.snapshot()
    assert snap is not None
    assert snap.source == "xplane"
    assert snap.latitude == 47.4


def test_xplane_snapshot_does_not_hold_power_gate():
    snap = SimSnapshot(
        connected=True,
        source="xplane",
        on_ground=True,
        ground_velocity_kt=0.0,
        alt_agl_ft=0.0,
        detail="X-Plane 12",
    )
    assert aircraft_is_powered(snap) is None
    assert compute_unpowered(snap, require_powered=True) is False
    assert compute_sterile(snap) is False


def test_xplane_stock_sources_off_hold_power_gate():
    snap = SimSnapshot(
        connected=True,
        source="xplane",
        on_ground=True,
        main_bus_voltage=0.0,
        electrical={
            "ELECTRICAL BUS VOLTAGE:1": 0.0,
            "XP GENERATOR ON:1": 0.0,
            "APU GENERATOR SWITCH": 0.0,
            "XP APU RUNNING": 0.0,
            "XP ENG RUNNING:1": 0.0,
            "XP ENG N1:1": 0.0,
        },
        detail="X-Plane 12",
    )
    assert aircraft_is_powered(snap) is False
    assert compute_unpowered(snap, require_powered=True) is True


def test_xplane_destinations_localhost_and_auto():
    mon = XPlaneUdpMonitor(host="127.0.0.1", port=49000, detect_fn=lambda: [])
    assert mon.destinations() == [("127.0.0.1", 49000)]
    mon.set_endpoint("auto", 49000)
    assert mon.destinations() == [("127.0.0.1", 49000)]
    mon._beacon_host = "192.168.1.20"
    mon._beacon_port = 49000
    assert mon.destinations() == [("127.0.0.1", 49000), ("192.168.1.20", 49000)]
    mon.set_endpoint("10.0.0.5", "49010")
    assert mon.destinations() == [("10.0.0.5", 49010)]


def test_xplane_sterile_uses_agl_and_gs():
    air = SimSnapshot(
        connected=True,
        source="xplane",
        on_ground=False,
        alt_agl_ft=400.0,
        ground_velocity_kt=140.0,
    )
    assert compute_sterile(air) is True
    taxi = SimSnapshot(
        connected=True,
        source="xplane",
        on_ground=True,
        alt_agl_ft=0.0,
        ground_velocity_kt=45.0,
    )
    assert compute_sterile(taxi) is True
