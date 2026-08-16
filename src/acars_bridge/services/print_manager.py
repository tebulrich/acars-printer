from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime

from acars_bridge.models.messages import MessageRepository, StoredMessage
from acars_bridge.printing.base import MessagePrinter, PrinterError, PrinterSettings
from acars_bridge.printing.companion_qr import pairing_caption, should_emit_pairing_qr
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
        self._pairing_url: str | None = None
        self._pairing_emitted = False

    def set_pairing_url(self, url: str | None) -> None:
        cleaned = (url or "").strip() or None
        with self._lock:
            if cleaned != self._pairing_url:
                self._pairing_emitted = False
            self._pairing_url = cleaned

    def _take_pairing_url(self) -> str | None:
        with self._lock:
            url = self._pairing_url
            if not url or self._pairing_emitted:
                return None
            self._pairing_emitted = True
            return url

    def pairing_state(self) -> tuple[str | None, bool]:
        with self._lock:
            return self._pairing_url, self._pairing_emitted

    def restore_pairing_state(self, url: str | None, emitted: bool) -> None:
        with self._lock:
            self._pairing_url = (url or "").strip() or None
            self._pairing_emitted = bool(emitted) and bool(self._pairing_url)

    def reset_pairing_qr(self) -> None:
        """Allow the next flight-plan strip to carry the phone QR again."""
        with self._lock:
            self._pairing_emitted = False

    def _with_pairing(
        self,
        body: str,
        settings: PrinterSettings,
        *,
        ticket_type: str = "",
    ) -> tuple[str, PrinterSettings]:
        url, already = self.pairing_state()
        if not should_emit_pairing_qr(
            enabled=True,
            url=url or "",
            already=already,
            ticket_type=ticket_type,
        ):
            return body, settings
        taken = self._take_pairing_url()
        if not taken:
            return body, settings
        caption = pairing_caption(taken)
        if caption not in body:
            body = body.rstrip() + "\n\n" + caption + "\n"
        return body, replace(settings, pairing_url=taken)

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
        if not is_reprint:
            body, settings = self._with_pairing(body, settings, ticket_type=ticket_type)
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

    def feed(self, settings: PrinterSettings, lines: int | None = None) -> None:
        feed_fn = getattr(self._printer, "feed", None)
        if not callable(feed_fn):
            raise PrinterError("This printer backend does not support feed.")
        with self._lock:
            feed_fn(settings, lines)
