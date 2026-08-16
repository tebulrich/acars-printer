from __future__ import annotations

from acars_bridge.models.messages import StoredMessage
from acars_bridge.printing.base import PrinterError, PrinterSettings


class FakeMessagePrinter:
    def __init__(self) -> None:
        self.printed: list[tuple[int, str]] = []
        self.pairing_urls: list[str] = []
        self.feed_count = 0
        self.should_fail = False
        self.failure_message = "Simulated printer failure"

    def print(self, message: StoredMessage, formatted_body: str, settings: PrinterSettings) -> None:
        if self.should_fail:
            raise PrinterError(self.failure_message)
        self.printed.append((message.id, formatted_body))
        if settings.pairing_url:
            self.pairing_urls.append(settings.pairing_url)

    def feed(self, settings: PrinterSettings, lines: int | None = None) -> None:
        del settings
        self.feed_count += max(1, int(lines or 1))

    def name(self) -> str:
        return "fake"
