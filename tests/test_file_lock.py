from __future__ import annotations

import os
from pathlib import Path

from acars_bridge.single_instance import (
    SingleInstanceError,
    acquire_lock,
    force_quit_pid,
    process_alive,
)


def test_process_alive_self() -> None:
    assert process_alive(os.getpid()) is True


def test_process_alive_bogus() -> None:
    assert process_alive(0) is False
    assert process_alive(-1) is False


def test_force_quit_refuses_self() -> None:
    ok, detail = force_quit_pid(os.getpid())
    assert ok is False
    assert "current" in detail.lower()


def test_acquire_lock_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "app.lock"
    lock = acquire_lock(path)
    assert path.exists()
    try:
        acquire_lock(path)
        raise AssertionError("expected SingleInstanceError")
    except SingleInstanceError:
        pass
    lock.release()
    lock2 = acquire_lock(path)
    lock2.release()
