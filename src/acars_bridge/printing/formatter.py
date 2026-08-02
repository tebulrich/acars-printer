from __future__ import annotations

from datetime import UTC, datetime

from acars_bridge.hoppie.types import MessageType
from acars_bridge.models.messages import StoredMessage
from acars_bridge.printing.base import PrinterSettings


class ThermalMessageFormatter:
    def format(
        self,
        message: StoredMessage,
        settings: PrinterSettings,
        now: datetime | None = None,
    ) -> str:
        width = settings.characters_per_line()
        now = now or datetime.now(UTC)
        rule = "-" * width
        try:
            type_label = MessageType(message.message_type).label()
        except ValueError:
            type_label = message.message_type.upper()

        lines = [
            rule,
            self._center("ACARS PRINT BRIDGE", width),
            rule,
            self._wrap_join(
                f"UTC: {now.astimezone(UTC).strftime('%d %b %Y').upper()}  "
                f"{now.astimezone(UTC).strftime('%H%M')}Z",
                width,
            ),
            self._wrap_join(f"FLT: {message.callsign}", width),
            self._wrap_join(f"FROM: {message.sender or 'UNKNOWN'}", width),
            self._wrap_join(f"TYPE: {type_label}", width),
            rule,
        ]
        for body_line in message.normalized_body.split("\n"):
            lines.extend(self._wrap_lines(body_line, width))
        msg_id = (message.fingerprint or f"ID{message.id:08d}")[:8].upper()
        lines.extend([rule, self._wrap_join(f"MSG ID: {msg_id}", width), ""])
        return "\n".join(lines)

    def test_page(self, settings: PrinterSettings, now: datetime | None = None) -> str:
        width = settings.characters_per_line()
        now = now or datetime.now(UTC)
        rule = "-" * width
        return "\n".join(
            [
                rule,
                self._center("ACARS PRINT BRIDGE", width),
                rule,
                self._center("TEST PRINT", width),
                f"UTC: {now.astimezone(UTC).strftime('%d %b %Y').upper()}  "
                f"{now.astimezone(UTC).strftime('%H%M')}Z",
                f"WIDTH: {settings.paper_width}mm ({width} cols)",
                rule,
                "The quick brown fox jumps over the lazy dog 0123456789",
                rule,
                "",
            ]
        )

    def _center(self, text: str, width: int) -> str:
        text = text[:width]
        pad = max(0, (width - len(text)) // 2)
        return (" " * pad) + text

    def _wrap_join(self, line: str, width: int) -> str:
        return "\n".join(self._wrap_lines(line, width))

    def _wrap_lines(self, line: str, width: int) -> list[str]:
        if line == "":
            return [""]
        if len(line) <= width:
            return [line]

        import re

        tokens = re.split(r"(\s+)", line)
        rows: list[str] = []
        current = ""
        for token in tokens:
            if token == "":
                continue
            if token.isspace():
                if current:
                    current += token
                continue
            if len(token) > width:
                if current:
                    rows.append(current.rstrip())
                    current = ""
                for i in range(0, len(token), width):
                    rows.append(token[i : i + width])
                continue
            candidate = token if current == "" else current + token
            if len(candidate.rstrip()) <= width:
                current = candidate
            else:
                if current:
                    rows.append(current.rstrip())
                current = token
        if current:
            rows.append(current.rstrip())
        return rows or [""]
