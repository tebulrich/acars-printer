from __future__ import annotations

from datetime import UTC, datetime

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
        req_label, body = self._split_inforeq(message)

        lines = [
            rule,
            self._wrap_join(
                f"{now.astimezone(UTC).strftime('%d %b %Y').upper()}  "
                f"{now.astimezone(UTC).strftime('%H%M')}Z",
                width,
            ),
            self._wrap_join(f"FLT  {message.callsign}", width),
        ]
        if req_label:
            lines.append(self._wrap_join(f"REQ  {req_label}", width))
        else:
            from_station = message.sender or message.to_station or "UNKNOWN"
            lines.append(self._wrap_join(f"FROM {from_station}", width))
        lines.append(rule)
        for body_line in body.split("\n"):
            lines.extend(self._wrap_lines(body_line, width))
        lines.extend([rule, ""])
        return "\n".join(lines)

    @staticmethod
    def _split_inforeq(message: StoredMessage) -> tuple[str | None, str]:
        """For inforeq, leading packet line (VATATIS/METAR/…) becomes REQ."""
        from acars_bridge.hoppie.atis_text import inforeq_request_label

        body = message.normalized_body or ""
        if message.message_type != "inforeq":
            return None, body
        label = inforeq_request_label(body)
        if not label:
            return None, body
        _first, _sep, rest = body.partition("\n")
        return label, rest

    def test_page(self, settings: PrinterSettings, now: datetime | None = None) -> str:
        width = settings.characters_per_line()
        now = now or datetime.now(UTC)
        rule = "-" * width
        return "\n".join(
            [
                rule,
                self._center("TEST PRINT", width),
                f"{now.astimezone(UTC).strftime('%d %b %Y').upper()}  "
                f"{now.astimezone(UTC).strftime('%H%M')}Z",
                f"WIDTH {settings.paper_width}mm ({width} cols)",
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
