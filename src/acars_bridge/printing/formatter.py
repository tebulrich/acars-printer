from __future__ import annotations

from datetime import UTC, datetime

from acars_bridge.hoppie.atis_text import inforeq_station_title
from acars_bridge.models.messages import StoredMessage
from acars_bridge.printing.base import PrinterSettings


class ThermalMessageFormatter:
    """Format uplinks like a cockpit ACARS MU hardcopy strip.

    Layout mirrors common flight-deck printer wrappers seen on sample
    printouts (airline/MU-specific, not an ARINC standard text):

        ACARS BEGIN
        <print date/time>  REG <registration>

        <message date/time>

        <body>
        ACARS END
    """

    def format(
        self,
        message: StoredMessage,
        settings: PrinterSettings,
        now: datetime | None = None,
    ) -> str:
        width = settings.characters_per_line()
        print_at = now or datetime.now(UTC)
        msg_at = self._message_time(message) or print_at
        title, body = self._title_and_body(message)
        # Only a real tail from Settings — never the Hoppie callsign as REG.
        reg = (settings.aircraft_registration or "").strip().upper() or None

        lines: list[str] = [
            "ACARS BEGIN",
            self._header_line(print_at, reg),
            "",
            self._stamp(msg_at),
            "",
        ]
        if title:
            lines.append(self._wrap_join(title, width))
        elif message.message_type != "inforeq":
            from_station = (message.sender or message.to_station or "").strip()
            if from_station:
                lines.append(self._wrap_join(f"FROM {from_station.upper()}", width))
        for body_line in body.split("\n"):
            lines.extend(self._wrap_lines(body_line, width))
        lines.append("")
        lines.append("ACARS END")
        lines.append("")
        return "\n".join(lines)

    def test_page(self, settings: PrinterSettings, now: datetime | None = None) -> str:
        width = settings.characters_per_line()
        now = now or datetime.now(UTC)
        reg = (settings.aircraft_registration or "TEST").strip().upper() or "TEST"
        ruler = "".join(str(i % 10) for i in range(1, width + 1))
        return "\n".join(
            [
                "ACARS BEGIN",
                self._header_line(now, reg),
                "",
                self._stamp(now),
                "",
                "TEST PRINT",
                f"WIDTH {settings.paper_width}mm / {width} COLS",
                "",
                ruler,
                "The quick brown fox jumps over the lazy dog 0123456789",
                "",
                "ACARS END",
                "",
            ]
        )

    @staticmethod
    def _stamp(when: datetime) -> str:
        return when.astimezone(UTC).strftime("%d %b %Y  %H%MZ").upper()

    @classmethod
    def _header_line(cls, when: datetime, registration: str | None) -> str:
        stamp = cls._stamp(when)
        if registration:
            return f"{stamp}  REG {registration}"
        return stamp

    @staticmethod
    def _message_time(message: StoredMessage) -> datetime | None:
        raw = (message.received_at or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def _title_and_body(message: StoredMessage) -> tuple[str | None, str]:
        from acars_bridge.hoppie.atis_text import (
            atis_reply_unavailable,
            inforeq_request_label,
        )

        body = (message.normalized_body or "").rstrip()
        if message.message_type != "inforeq":
            return None, body

        label = inforeq_request_label(body)
        if label:
            _first, _sep, rest = body.partition("\n")
            body = rest.rstrip()
        else:
            return None, body

        title = inforeq_station_title(label)
        if not title:
            return None, body

        # Real ATIS text often already starts with "EDDH DEP ATIS …" — don't duplicate.
        head = body.split("\n", 1)[0].upper()
        if title.upper() in head or (
            len(title) >= 4 and title[:4].upper() in head and "ATIS" in head
        ):
            return None, body
        # Unavailable stubs need the station on the strip.
        if atis_reply_unavailable(body) or not body.strip():
            return title, body or "NOT AVAILABLE"
        # METAR/TAF replies are often bare text without the ICAO in a header line.
        if label.split()[0] in {"METAR", "TAF", "SHORTTAF", "SHORTFAF"}:
            icao = title.split()[-1] if title.split() else ""
            if icao and icao not in body.upper():
                return title, body
        return None, body

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
