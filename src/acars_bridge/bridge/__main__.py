"""JSON-line bridge entrypoint for Tauri.

  python -m acars_bridge.bridge serve
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import TextIO

from acars_bridge.bridge.runtime import BridgeRuntime
from acars_bridge.config import AppPaths
from acars_bridge.services.session import build_session
from acars_bridge.single_instance import SingleInstanceError, acquire_lock

# Dedicated NDJSON stream — third-party print()/logging must not touch this.
_PROTOCOL_OUT: TextIO = sys.stdout


def _emit(payload: dict) -> None:
    _PROTOCOL_OUT.write(json.dumps(payload, default=str) + "\n")
    _PROTOCOL_OUT.flush()


def isolate_protocol_stdout() -> TextIO:
    """Send casual ``print()`` noise to stderr so NDJSON on stdout stays clean.

    Returns the previous stdout (protocol stream).
    """
    global _PROTOCOL_OUT
    protocol = sys.stdout
    _PROTOCOL_OUT = protocol
    try:
        sys.stdout = sys.stderr
    except Exception:
        pass
    return protocol


def _ok(data) -> dict:
    return {"ok": True, "data": data}


def _err(message: str) -> dict:
    return {"ok": False, "error": message}


def _build_runtime(*, data_dir: str | None = None, fake_printer: bool = False) -> BridgeRuntime:
    if data_dir:
        paths = AppPaths.for_testing(Path(data_dir))
    else:
        paths = AppPaths.default()
    session = build_session(paths, use_fake_printer=fake_printer)
    return BridgeRuntime(session, clear_messages_on_boot=True)


def serve() -> int:
    from acars_bridge.native_runtime import prepare_frozen_natives

    prepare_frozen_natives()
    isolate_protocol_stdout()
    data_dir = os.environ.get("ACARS_BRIDGE_DATA_DIR")
    fake = os.environ.get("ACARS_BRIDGE_FAKE_PRINTER", "").strip() in {"1", "true", "yes"}
    lock = None
    try:
        if not data_dir:
            lock = acquire_lock(AppPaths.default().root / "app.lock")
    except SingleInstanceError as exc:
        _emit(_err(str(exc)))
        return 1
    except Exception:
        pass

    try:
        runtime = _build_runtime(data_dir=data_dir, fake_printer=fake)
    except Exception as exc:  # noqa: BLE001
        _emit(_err(f"Failed to start bridge: {exc}\n{traceback.format_exc(limit=4)}"))
        return 1

    _emit(_ok({"ready": True, "log": str(runtime.debug.path)}))

    try:
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            if line in {"quit", "exit"}:
                break
            try:
                req = json.loads(line)
                if not isinstance(req, dict):
                    raise ValueError("Request must be a JSON object")
                command = str(req.get("command") or "").strip()
                args = req.get("args") or {}
                if not isinstance(args, dict):
                    raise ValueError("args must be a JSON object")
                if not command:
                    raise ValueError("command is required")
            except Exception as exc:  # noqa: BLE001
                _emit(_err(f"Invalid request: {exc}"))
                continue
            _emit(runtime.handle(command, args))
            for event in runtime.drain_events():
                _emit(event)
            if command == "quit":
                break
    finally:
        runtime.shutdown()
        if lock is not None:
            try:
                lock.release()
            except Exception:
                pass
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].strip() in {"serve", "--serve"}:
        return serve()
    command = argv[0].strip()
    raw_args = argv[1] if len(argv) > 1 else "{}"
    try:
        args = json.loads(raw_args) if raw_args else {}
        if not isinstance(args, dict):
            raise ValueError("Arguments must be a JSON object")
    except Exception as exc:  # noqa: BLE001
        _emit(_err(f"Invalid JSON args: {exc}"))
        return 2
    runtime = _build_runtime(
        data_dir=os.environ.get("ACARS_BRIDGE_DATA_DIR"),
        fake_printer=True,
    )
    try:
        _emit(runtime.handle(command, args))
    finally:
        runtime.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
