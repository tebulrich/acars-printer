from __future__ import annotations

from acars_bridge.models.messages import StoredMessage
from acars_bridge.printing.base import PrinterError, PrinterSettings


class FakeMessagePrinter:
    def __init__(self) -> None:
        self.printed: list[tuple[int, str]] = []
        self.should_fail = False
        self.failure_message = "Simulated printer failure"

    def print(self, message: StoredMessage, formatted_body: str, settings: PrinterSettings) -> None:
        if self.should_fail:
            raise PrinterError(self.failure_message)
        self.printed.append((message.id, formatted_body))

    def name(self) -> str:
        return "fake"
