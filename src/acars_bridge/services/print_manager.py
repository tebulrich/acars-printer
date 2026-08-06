from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime

from acars_bridge.models.messages import MessageRepository, StoredMessage
from acars_bridge.printing.base import MessagePrinter, PrinterError, PrinterSettings
from acars_bridge.printing.formatter import ThermalMessageFormatter

log = logging.getLogger(__name__)

TICKET_GAP_SECONDS = 0.35


class PrintManager:
    """Serializes all thermal output onto one worker so cuts never overlap."""

    def __init__(
        self,
        repo: MessageRepository,
        printer: MessagePrinter,
        formatter: ThermalMessageFormatter | None = None,
    ) -> None:
        self._repo = repo
        self._printer = printer
        self._formatter = formatter or ThermalMessageFormatter()
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="printer")

    def shutdown(self, *, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def submit(self, job: Callable[[], None]) -> Future[None]:
        """Run a print-related job on the serial printer worker."""

        def wrapped() -> None:
            try:
                job()
            except Exception:
                log.exception("printer worker job failed")

        return self._executor.submit(wrapped)

    def print_message(
        self,
        message: StoredMessage,
        settings: PrinterSettings,
        *,
        is_reprint: bool = False,
    ) -> str:
        body = self._formatter.format(message, settings)
        return self._emit(message, body, settings, is_reprint=is_reprint)

    def print_ticket(
        self,
        body: str,
        settings: PrinterSettings,
        *,
        callsign: str,
        ticket_type: str,
        sender: str = "SIMBRIEF",
        is_reprint: bool = False,
    ) -> str:
        """Print a dispatch ticket as-is (no ACARS BEGIN/END wrapper)."""
        digest = hashlib.sha256(f"{ticket_type}\n{body}".encode()).hexdigest()[:24]
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        fingerprint = f"ticket:{ticket_type}:{digest}:{stamp}"
        stored = self._repo.insert_ticket(
            callsign=callsign,
            ticket_type=ticket_type,
            body=body,
            fingerprint=fingerprint,
            sender=sender,
        )
        return self._emit(stored, body, settings, is_reprint=is_reprint)

    def print_tickets(
        self,
        tickets: list[tuple[str, str]],
        settings: PrinterSettings,
        *,
        callsign: str,
        sender: str = "SIMBRIEF",
        gap_seconds: float = TICKET_GAP_SECONDS,
    ) -> list[str]:
        results: list[str] = []
        for index, (ticket_type, body) in enumerate(tickets):
            if index and gap_seconds > 0:
                time.sleep(gap_seconds)
            results.append(
                self.print_ticket(
                    body,
                    settings,
                    callsign=callsign,
                    ticket_type=ticket_type,
                    sender=sender,
                )
            )
        return results

    def _emit(
        self,
        message: StoredMessage,
        body: str,
        settings: PrinterSettings,
        *,
        is_reprint: bool,
    ) -> str:
        printer_name = f"{self._printer.name()}:{settings.destination}"
        with self._lock:
            try:
                self._printer.print(message, body, settings)
                self._repo.create_print_job(
                    message.id, printer_name, "printed", is_reprint=is_reprint
                )
                return "printed"
            except PrinterError as exc:
                self._repo.create_print_job(
                    message.id,
                    printer_name,
                    "failed",
                    error_message=str(exc)[:2000],
                    is_reprint=is_reprint,
                )
                return "failed"

    def test_print(self, settings: PrinterSettings) -> None:
        body = self._formatter.test_page(settings)
        dummy = StoredMessage(
            id=0,
            fingerprint="test",
            direction="out",
            callsign="TEST",
            sender=None,
            recipient=None,
            to_station=None,
            message_type="telex",
            raw_payload="TEST",
            normalized_body="TEST",
            min=None,
            mrn=None,
            ra=None,
            send_status=None,
            received_at="",
        )
        with self._lock:
            self._printer.print(dummy, body, settings)
