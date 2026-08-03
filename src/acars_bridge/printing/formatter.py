from __future__ import annotations

from datetime import UTC, datetime

from acars_bridge.models.messages import StoredMessage
from acars_bridge.printing.base import PrinterSettings


class ThermalMessageFormatter:
    """Format uplinks like a cockpit ACARS/D-ATIS thermal strip.

    Real D-ATIS and company prints are mostly the uplink text itself (see e.g.
    ICAO D-ATIS samples: time + ATIS body, no synthetic request labels). We do
    not invent FLT/REQ lines from Hoppie packet names such as VATATIS EDDH_D.
    """

    def format(
        self,
        message: StoredMessage,
        settings: PrinterSettings,
        now: datetime | None = None,
    ) -> str:
        width = settings.characters_per_line()
        now = now or datetime.now(UTC)
        body = self._print_body(message)
        stamp = now.astimezone(UTC).strftime("%H%M") + "Z"

        lines: list[str] = [stamp]
        # Weather/ATIS uplinks are the report text alone. CPDLC/telex keep a
        # short FROM line so the station is visible without looking like an app.
        if message.message_type != "inforeq":
            from_station = (message.sender or message.to_station or "").strip()
            if from_station:
                lines.append(self._wrap_join(f"FROM {from_station.upper()}", width))
        lines.append("")
        for body_line in body.split("\n"):
            lines.extend(self._wrap_lines(body_line, width))
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _print_body(message: StoredMessage) -> str:
        """Body for the strip; drop Hoppie inforeq packet labels from print."""
        from acars_bridge.hoppie.atis_text import inforeq_request_label

        body = (message.normalized_body or "").rstrip()
        if message.message_type != "inforeq":
            return body
        label = inforeq_request_label(body)
        if not label:
            return body
        _first, _sep, rest = body.partition("\n")
        return rest.rstrip()

    def test_page(self, settings: PrinterSettings, now: datetime | None = None) -> str:
        width = settings.characters_per_line()
        now = now or datetime.now(UTC)
        stamp = now.astimezone(UTC).strftime("%H%M") + "Z"
        ruler = "".join(str(i % 10) for i in range(1, width + 1))
        return "\n".join(
            [
                stamp,
                "TEST PRINT",
                f"WIDTH {settings.paper_width}mm / {width} COLS",
                "",
                ruler,
                "The quick brown fox jumps over the lazy dog 0123456789",
                "",
            ]
        )

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
