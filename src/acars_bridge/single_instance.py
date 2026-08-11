"""Process single-instance lock (file + PID), without Qt."""

from __future__ import annotations

import atexit
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


class SingleInstanceError(RuntimeError):
    """Another live instance holds the lock."""

    def __init__(self, message: str, *, pid: int | None = None) -> None:
        super().__init__(message)
        self.pid = pid


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        out = (completed.stdout or "").strip().lower()
        return str(pid) in out and "no tasks" not in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def force_quit_pid(pid: int) -> tuple[bool, str]:
    if pid <= 0:
        return False, "Invalid PID"
    if pid == os.getpid():
        return False, "Refusing to kill the current process"
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)
        detail = (completed.stdout or completed.stderr or "").strip()
        if completed.returncode == 0 or not process_alive(pid):
            return True, detail or f"Ended PID {pid}."
        return False, detail or f"taskkill failed for PID {pid}."
    try:
        os.kill(pid, 9)
    except OSError as exc:
        return False, str(exc)
    return True, f"Ended PID {pid}."


@dataclass
class FileLock:
    path: Path
    _held: bool = False

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def acquire_lock(path: Path, *, force: bool = False, stale_seconds: float = 5.0) -> FileLock:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8").strip()
            pid = int(raw.split()[0]) if raw else 0
        except (OSError, ValueError):
            pid = 0
        mtime = path.stat().st_mtime if path.exists() else 0
        stale = (time.time() - mtime) > stale_seconds and not process_alive(pid)
        if process_alive(pid) and not force and not stale:
            raise SingleInstanceError(
                f"ACARS Print Bridge is already running (PID {pid}).",
                pid=pid,
            )
        if force and process_alive(pid):
            force_quit_pid(pid)
            time.sleep(0.3)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    lock = FileLock(path=path, _held=True)
    atexit.register(lock.release)
    return lock
