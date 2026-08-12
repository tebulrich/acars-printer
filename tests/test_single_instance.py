from __future__ import annotations

import os

import pytest

from acars_bridge.single_instance import (
    SingleInstanceError,
    acquire_lock,
    process_alive,
)


def test_process_alive_self():
    assert process_alive(os.getpid()) is True


def test_process_alive_bogus():
    assert process_alive(0) is False
    assert process_alive(-1) is False
    assert process_alive(2_147_483_646) is False


def test_acquire_lock_reclaims_dead_pid(tmp_path):
    lock_path = tmp_path / "app.lock"
    lock_path.write_text("2147483646\n", encoding="utf-8")
    held = acquire_lock(lock_path)
    assert held.path == lock_path
    assert lock_path.read_text(encoding="utf-8").strip() == str(os.getpid())
    held.release()


def test_acquire_lock_blocks_live_pid(tmp_path):
    lock_path = tmp_path / "app.lock"
    first = acquire_lock(lock_path)
    with pytest.raises(SingleInstanceError, match="already running"):
        acquire_lock(lock_path)
    first.release()


def test_emit_tolerates_closed_stdout(monkeypatch):
    from acars_bridge.bridge import __main__ as bridge_main

    class _Broken:
        def write(self, _data):
            raise OSError(22, "Invalid argument")

        def flush(self):
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr(bridge_main, "_PROTOCOL_OUT", _Broken())
    bridge_main._emit({"ok": False, "error": "already running"})
