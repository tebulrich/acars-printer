from __future__ import annotations

from datetime import UTC, datetime

from acars_bridge.hoppie.atis_text import inforeq_station_title
from acars_bridge.hoppie.sanitize import scrub_message_body
from acars_bridge.models.messages import StoredMessage
from acars_bridge.printing.base import PrinterSettings


class ThermalMessageFormatter:
    """Format uplinks like SimBrief tickets from this app.

    Layout:

        ACARS START
        ================================
        D-AILA ----  DLH4MC 04AUG 1809Z
        --------------------------------
        <body>
        ================================
        ACARS END

    Registration is optional (Settings). If empty, omit both the tail and ``----``.
    """

    def format(
        self,
        message: StoredMessage,
        settings: PrinterSettings,
        now: datetime | None = None,
    ) -> str:
        width = settings.characters_per_line()
        when = self._message_time(message) or now or datetime.now(UTC)
        title, body = self._title_and_body(message)
        reg = (settings.aircraft_registration or "").strip().upper() or None
        callsign = (message.callsign or "").strip().upper() or None
        bar = "=" * max(8, width)
        dash = "-" * max(8, width)

        lines: list[str] = [
            "ACARS START",
            bar,
            self._header_line(when, reg, callsign, width),
            dash,
        ]
        if title:
            lines.extend(self._wrap_lines(title.upper(), width))
        for body_line in body.split("\n"):
            lines.extend(self._wrap_lines(body_line.upper(), width))
        lines.append(bar)
        lines.append("ACARS END")
        lines.append("")
        return "\n".join(lines)

    def test_page(self, settings: PrinterSettings, now: datetime | None = None) -> str:
        """Demo strip matching a real airline PDC hardcopy (for format comparison).

        Uses the configured aircraft registration as-is (empty = omit tail / ``----``).
        """
        # Fixed stamp from the reference photo so side-by-side comparison is easy.
        when = now or datetime(2026, 8, 4, 18, 9, tzinfo=UTC)
        demo = StoredMessage(
            id=0,
            fingerprint="demo",
            direction="in",
            callsign="DLH4MC",
            sender="EDDF_DEL",
            recipient="DLH4MC",
            to_station=None,
            message_type="telex",
            raw_payload="DEMO",
            normalized_body=(
                "CLD 1807 260804 EDDF PDC 001\n"
                "DLH4MCCLRD TO EDDM OFF 18 VIA\n"
                "CINDY8S SQUAWK 1000 NEXT FREQ\n"
                "122.035 ATIS G REPORT TOBT VIA\n"
                "VATS.IM|VDGS REPORT READY ON\n"
                "122.035 ACC TSAT"
            ),
            min=None,
            mrn=None,
            ra=None,
            send_status=None,
            received_at=when.isoformat(),
        )
        return self.format(demo, settings, now=when)

    @staticmethod
    def _stamp(when: datetime) -> str:
        # Real strips: 04AUG 1805Z (no year, no space between day and month).
        return when.astimezone(UTC).strftime("%d%b %H%MZ").upper()

    @classmethod
    def _header_line(
        cls,
        when: datetime,
        registration: str | None,
        callsign: str | None,
        width: int,
    ) -> str:
        """``D-AILA ----  DLH4MC 04AUG 1809Z`` — omit tail/``----`` if no registration."""
        stamp = cls._stamp(when)
        if registration and callsign:
            line = f"{registration} ----  {callsign} {stamp}"
        elif registration:
            # No callsign: keep stamp near the right edge like short weather strips.
            left = f"{registration} ----"
            gap = max(1, width - len(left) - len(stamp))
            line = left + (" " * gap) + stamp
        elif callsign:
            line = f"{callsign} {stamp}"
        else:
            line = stamp
        if len(line) <= width:
            return line
        return line[:width]

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

        body = scrub_message_body(message.normalized_body or "")
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
