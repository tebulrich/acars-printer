from __future__ import annotations

import io
import json
import sys

from acars_bridge.bridge.__main__ import _emit, isolate_protocol_stdout


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
