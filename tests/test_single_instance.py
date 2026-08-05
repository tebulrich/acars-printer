from __future__ import annotations

import os

from acars_bridge.ui.app import _force_quit_pid, _process_alive


def test_process_alive_self():
    assert _process_alive(os.getpid()) is True


def test_process_alive_bogus():
    assert _process_alive(0) is False
    assert _process_alive(-1) is False
    # Extremely unlikely to be a live PID on Windows.
    assert _process_alive(2_147_483_646) is False


def test_force_quit_refuses_self():
    ok, detail = _force_quit_pid(os.getpid())
    assert ok is False
    assert "current" in detail.lower()


def test_force_quit_invalid():
    ok, detail = _force_quit_pid(0)
    assert ok is False
    assert "invalid" in detail.lower()
