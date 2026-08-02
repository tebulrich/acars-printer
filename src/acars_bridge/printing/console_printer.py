from __future__ import annotations

import sys

from acars_bridge.models.messages import StoredMessage
from acars_bridge.printing.base import PrinterSettings


class ConsoleMessagePrinter:
    def print(self, message: StoredMessage, formatted_body: str, settings: PrinterSettings) -> None:
        sys.stdout.write(formatted_body)
        if not formatted_body.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()

    def name(self) -> str:
        return "console"
