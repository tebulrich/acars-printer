from __future__ import annotations

import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class DebugLog:
    """Ring-buffer + append-only file log for UI/support pastebacks.

    Never write secrets here — callers must pass already-redacted values.
    """

    def __init__(
        self,
        path: Path,
        *,
        max_lines: int = 800,
        max_file_bytes: int = 1_500_000,
    ) -> None:
        self.path = path
        self._max_lines = max_lines
        self._max_file_bytes = max_file_bytes
        self._lock = threading.Lock()
        self._lines: deque[str] = deque(maxlen=max_lines)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._rotate_if_needed()
        self.info(
            "session_start",
            path=str(self.path),
        )

    def info(self, event: str, **fields: Any) -> None:
        self._write("INFO", event, fields)

    def action(self, event: str, **fields: Any) -> None:
        self._write("ACTION", event, fields)

    def error(self, event: str, **fields: Any) -> None:
        self._write("ERROR", event, fields)

    def toast(self, message: str, *, error: bool = False) -> None:
        self._write(
            "TOAST",
            "error" if error else "ok",
            {"message": message},
        )

    def text(self) -> str:
        with self._lock:
            return "\n".join(self._lines)

    def paste_block(self, *, header: dict[str, Any] | None = None) -> str:
        """Ready-to-paste block for chat / bug reports."""
        lines = ["=== ACARS Print Bridge debug log ==="]
        if header:
            for key, value in header.items():
                lines.append(f"{key}: {value}")
            lines.append("---")
        body = self.text().strip()
        lines.append(body if body else "(empty)")
        lines.append("=== end ===")
        return "\n".join(lines)

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()
            self.path.write_text("", encoding="utf-8")
        self.info("log_cleared")

    def _write(self, level: str, event: str, fields: dict[str, Any]) -> None:
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        extras = " ".join(f"{key}={_fmt(value)}" for key, value in fields.items())
        line = f"{stamp} [{level}] {event}"
        if extras:
            line = f"{line} {extras}"
        with self._lock:
            self._lines.append(line)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def _rotate_if_needed(self) -> None:
        if not self.path.exists():
            return
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size <= self._max_file_bytes:
            return
        try:
            raw = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        keep = raw[-self._max_file_bytes // 2 :]
        cut = keep.find("\n")
        if cut >= 0:
            keep = keep[cut + 1 :]
        try:
            self.path.write_text(
                f"# rotated at {datetime.now(UTC).isoformat()}\n{keep}",
                encoding="utf-8",
            )
        except OSError:
            return


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value).replace("\n", "\\n").replace("\r", "")
    if " " in text or "\t" in text:
        return f'"{text}"'
    return text
