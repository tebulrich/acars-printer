"""Bridge power-gate / settle toasts after Tauri refactor (Qt parity)."""

from __future__ import annotations

from pathlib import Path

import pytest

from acars_bridge.bridge.runtime import BridgeRuntime, FakeTapService
from acars_bridge.config import AppPaths
from acars_bridge.services.session import build_session
from acars_bridge.services.sterile import SterileGate
from acars_bridge.simconnect.monitor import SimSnapshot


class _FakeSim:
    def __init__(self) -> None:
        self._snap = SimSnapshot(connected=False, detail="fake")

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def snapshot(self) -> SimSnapshot:
        return self._snap

    def set(self, snap: SimSnapshot) -> None:
        self._snap = snap


def _cold() -> SimSnapshot:
    return SimSnapshot(
        connected=True,
        on_ground=True,
        ground_velocity_kt=0,
        alt_agl_ft=0,
        battery_on=False,
        main_bus_voltage=0.0,
        external_power_on=False,
        electrical={
            "ELECTRICAL MAIN BUS VOLTAGE": 0.0,
            "CIRCUIT GENERAL PANEL ON": 0.0,
            "NEW ELECTRICAL SYSTEM": 0.0,
        },
    )


def _live() -> SimSnapshot:
    return SimSnapshot(
        connected=True,
        on_ground=True,
        ground_velocity_kt=0,
        alt_agl_ft=0,
        battery_on=False,
        main_bus_voltage=28.0,
        external_power_on=True,
        electrical={
            "ELECTRICAL MAIN BUS VOLTAGE": 28.0,
            "CIRCUIT GENERAL PANEL ON": 1.0,
            "EXTERNAL POWER ON": 1.0,
            "NEW ELECTRICAL SYSTEM": 0.0,
        },
    )


@pytest.fixture
def powered_runtime(tmp_path: Path):
    clock = {"t": 100.0}
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    session.settings.set_printer_destination("fake")
    session.settings.set_print_when_powered(True)
    session.apply_sterile_settings()
    gate = session.sterile
    gate._power_on_settle_seconds = 10.0
    gate._flush_stagger_seconds = 0.0
    gate._now_fn = lambda: clock["t"]
    fake = _FakeSim()
    fake.set(_cold())
    session.simconnect = fake  # type: ignore[assignment]
    rt = BridgeRuntime(
        session,
        tap_factory=FakeTapService,
        clear_messages_on_boot=False,
        background_tick=False,
    )
    yield rt, fake, clock
    rt.shutdown()


def _toast_messages(rt: BridgeRuntime) -> list[str]:
    events = rt.drain_events()
    return [
        str(e["data"].get("message") or "")
        for e in events
        if e.get("event") == "toast" and isinstance(e.get("data"), dict)
    ]


def test_tick_toasts_settle_then_flushes_queue(powered_runtime) -> None:
    rt, fake, clock = powered_runtime
    ran: list[str] = []
    rt.tick()  # see cold
    assert rt.session.sterile.is_unpowered
    assert rt.session.sterile.run_or_defer_simbrief(lambda: ran.append("sb")) is True

    fake.set(_live())
    rt.tick()
    toasts = _toast_messages(rt)
    assert any("printing in 10 seconds" in m for m in toasts)
    assert rt.session.sterile.is_settling
    assert ran == []
    status = rt.build_status()
    assert "settle" in status["chips"]["pwr"].lower()

    clock["t"] = 110.0
    rt.tick()
    toasts = _toast_messages(rt)
    assert any("printing" in m.lower() for m in toasts)
    assert ran == ["sb"]
    assert not rt.session.sterile.is_blocking


def test_disable_require_powered_flushes_queue() -> None:
    gate = SterileGate(
        require_powered=True, flush_stagger_seconds=0, power_on_settle_seconds=0
    )
    ran: list[str] = []
    gate.update_from_snapshot(_cold())
    assert gate.run_or_defer_simbrief(lambda: ran.append("sb")) is True
    gate.set_require_powered(False)
    assert ran == ["sb"]
    assert not gate.is_blocking


def test_tick_does_not_spam_electrical_buses(powered_runtime) -> None:
    rt, fake, _clock = powered_runtime
    fake.set(_live())
    rt.tick()
    rt.tick()
    text = rt.debug.text()
    assert "electrical_buses" not in text


def test_rebuild_printer_keeps_outbound_session(tmp_path: Path) -> None:
    session = build_session(AppPaths.for_testing(tmp_path), use_fake_printer=True)
    assert session.outbound._session is session
    session.rebuild_printer(use_fake_printer=True)
    assert session.outbound._session is session
    session.close()
