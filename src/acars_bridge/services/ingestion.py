from __future__ import annotations

import time
from collections.abc import Callable

from acars_bridge.hoppie.atis_text import atis_reply_unavailable, vatatis_airport_key
from acars_bridge.hoppie.types import HoppieMessage
from acars_bridge.models.messages import MessageRepository, StoredMessage
from acars_bridge.models.settings import SettingsStore
from acars_bridge.printing.base import PrinterSettings
from acars_bridge.services.fingerprint import fingerprint_for
from acars_bridge.services.print_manager import PrintManager

# Plane clients often try ICAO_D then plain ICAO within a couple seconds.
_UNAVAILABLE_COOLDOWN_SEC = 120.0
# Brief pause after a message is stored so the strip feels like a real MU print.
AUTO_PRINT_DELAY_SECONDS = 1.0


class MessageIngestionService:
    def __init__(
        self,
        repo: MessageRepository,
        settings: SettingsStore,
        print_manager: PrintManager,
        *,
        print_delay_seconds: float = AUTO_PRINT_DELAY_SECONDS,
    ) -> None:
        self._repo = repo
        self._settings = settings
        self._print_manager = print_manager
        self._print_delay_seconds = max(0.0, float(print_delay_seconds))
        self._recent_unavailable: dict[tuple[str, str], float] = {}

    def ingest(
        self,
        messages: list[HoppieMessage],
        *,
        auto_print: bool | None = None,
        force_print: bool = False,
    ) -> dict[str, int]:
        stats = {"stored": 0, "printed": 0, "duplicates": 0, "failed_prints": 0}
        printable = self._settings.printable_types()
        do_print = self._settings.auto_print() if auto_print is None else auto_print
        printer_settings = PrinterSettings(
            destination=self._settings.printer_destination(),
            paper_width=self._settings.paper_width(),
            cut_enabled=self._settings.cut_enabled(),
            aircraft_registration=self._settings.aircraft_registration(),
        )

        for message in messages:
            fp = fingerprint_for(message)
            stored = self._repo.insert_inbound(message, fp)
            unavailable = atis_reply_unavailable(message.normalized_body)
            wants_print = do_print and message.message_type.value in printable
            if wants_print and unavailable and self._suppress_unavailable_fallback(message):
                wants_print = False
            if stored is None:
                stats["duplicates"] += 1
                # Re-print only real content refreshes — never spam "not available".
                if force_print and wants_print and not unavailable:
                    existing = self._repo.get_by_fingerprint(fp)
                    if existing is not None:
                        result = self._print_after_delay(
                            existing, printer_settings, is_reprint=True
                        )
                        if result == "printed":
                            stats["printed"] += 1
                        else:
                            stats["failed_prints"] += 1
                continue

            if not wants_print:
                stats["stored"] += 1
                continue

            result = self._print_after_delay(stored, printer_settings)
            if result == "printed":
                stats["printed"] += 1
            else:
                stats["failed_prints"] += 1
        return stats

    def _print_after_delay(
        self,
        message: StoredMessage,
        printer_settings: PrinterSettings,
        *,
        is_reprint: bool = False,
    ) -> str:
        if self._print_delay_seconds > 0:
            time.sleep(self._print_delay_seconds)
        return self._print_manager.print_message(
            message, printer_settings, is_reprint=is_reprint
        )

    def ingest_from_fetch(
        self,
        fetch: Callable[[str, str], list[HoppieMessage]],
        logon: str,
        callsign: str,
        *,
        auto_print: bool | None = None,
    ) -> dict[str, int]:
        return self.ingest(fetch(logon, callsign), auto_print=auto_print)

    def _suppress_unavailable_fallback(self, message: HoppieMessage) -> bool:
        """Print first 'not available' per airport; skip D/A fallback copies."""
        airport = vatatis_airport_key(message.normalized_body) or "_bare"
        key = (message.callsign.upper(), airport)
        now = time.monotonic()
        self._prune_unavailable(now)
        previous = self._recent_unavailable.get(key)
        if previous is not None and (now - previous) < _UNAVAILABLE_COOLDOWN_SEC:
            return True
        self._recent_unavailable[key] = now
        return False

    def _prune_unavailable(self, now: float) -> None:
        stale = [
            key
            for key, seen in self._recent_unavailable.items()
            if (now - seen) >= _UNAVAILABLE_COOLDOWN_SEC
        ]
        for key in stale:
            del self._recent_unavailable[key]
