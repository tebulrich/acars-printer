from __future__ import annotations

from acars_bridge.models.messages import MessageRepository, StoredMessage
from acars_bridge.printing.base import MessagePrinter, PrinterError, PrinterSettings
from acars_bridge.printing.formatter import ThermalMessageFormatter


class PrintManager:
    def __init__(
        self,
        repo: MessageRepository,
        printer: MessagePrinter,
        formatter: ThermalMessageFormatter | None = None,
    ) -> None:
        self._repo = repo
        self._printer = printer
        self._formatter = formatter or ThermalMessageFormatter()

    def print_message(
        self,
        message: StoredMessage,
        settings: PrinterSettings,
        *,
        is_reprint: bool = False,
    ) -> str:
        body = self._formatter.format(message, settings)
        printer_name = f"{self._printer.name()}:{settings.destination}"
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
        self._printer.print(dummy, body, settings)
