from __future__ import annotations

import io
import json
import sys

from acars_bridge.bridge.__main__ import (
    _emit,
    emit_handle_result,
    isolate_protocol_stdout,
)


def test_emit_handle_result_writes_events_before_response():
    """Shell reads until the non-event response; events after it are deferred."""
    out: list[dict] = []
    events = [
        {"ok": True, "event": "new_messages", "data": {"count": 3}},
        {"ok": True, "event": "status", "data": {"message_count": 3}},
    ]
    emit_handle_result(
        {"ok": True, "data": {"running": True}},
        events,
        emit=out.append,
    )
    assert [row.get("event") for row in out[:-1]] == ["new_messages", "status"]
    assert out[-1] == {"ok": True, "data": {"running": True}}
    assert "event" not in out[-1]


def test_isolate_protocol_stdout_keeps_ndjson_clean():
    protocol = io.StringIO()
    noise = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout = protocol
        sys.stderr = noise
        isolate_protocol_stdout()
        print("The media.width.pixel field of the printer profile is not set.")
        _emit({"ok": True, "data": {"ready": True}})
    finally:
        sys.stdout = old_out
        sys.stderr = old_err

    lines = [ln for ln in protocol.getvalue().splitlines() if ln.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["ok"] is True
    assert "media.width" in noise.getvalue()


def test_debug_log_path_prefers_exe_log_env(tmp_path, monkeypatch):
    from acars_bridge.bridge.runtime import _debug_log_path

    target = tmp_path / "next-to-exe" / "acars-print-bridge.log"
    monkeypatch.setenv("ACARS_BRIDGE_EXE_LOG", str(target))
    assert _debug_log_path(tmp_path / "fallback") == target

    monkeypatch.delenv("ACARS_BRIDGE_EXE_LOG", raising=False)
    assert _debug_log_path(tmp_path / "fallback") == tmp_path / "fallback" / "debug.log"
