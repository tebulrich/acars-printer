from __future__ import annotations

from collections.abc import Callable

from acars_bridge.hoppie.types import HoppieMessage
from acars_bridge.models.messages import MessageRepository
from acars_bridge.models.settings import SettingsStore
from acars_bridge.printing.base import PrinterSettings
from acars_bridge.services.fingerprint import fingerprint_for
from acars_bridge.services.print_manager import PrintManager


class MessageIngestionService:
    def __init__(
        self,
        repo: MessageRepository,
        settings: SettingsStore,
        print_manager: PrintManager,
    ) -> None:
        self._repo = repo
        self._settings = settings
        self._print_manager = print_manager

    def ingest(
        self,
        messages: list[HoppieMessage],
        *,
        auto_print: bool | None = None,
    ) -> dict[str, int]:
        stats = {"stored": 0, "printed": 0, "duplicates": 0, "failed_prints": 0}
        printable = self._settings.printable_types()
        do_print = self._settings.auto_print() if auto_print is None else auto_print
        printer_settings = PrinterSettings(
            destination=self._settings.printer_destination(),
            paper_width=self._settings.paper_width(),
            cut_enabled=self._settings.cut_enabled(),
        )

        for message in messages:
            fp = fingerprint_for(message)
            stored = self._repo.insert_inbound(message, fp)
            if stored is None:
                stats["duplicates"] += 1
                continue

            should_print = do_print and message.message_type.value in printable
            if not should_print:
                stats["stored"] += 1
                continue

            result = self._print_manager.print_message(stored, printer_settings)
            if result == "printed":
                stats["printed"] += 1
            else:
                stats["failed_prints"] += 1
        return stats

    def ingest_from_fetch(
        self,
        fetch: Callable[[str, str], list[HoppieMessage]],
        logon: str,
        callsign: str,
        *,
        auto_print: bool | None = None,
    ) -> dict[str, int]:
        return self.ingest(fetch(logon, callsign), auto_print=auto_print)
