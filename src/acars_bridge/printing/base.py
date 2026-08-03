from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from acars_bridge.models.messages import StoredMessage


@dataclass(frozen=True, slots=True)
class PrinterSettings:
    destination: str
    paper_width: str = "80"
    cut_enabled: bool = True
    character_width_override: int | None = None

    def characters_per_line(self) -> int:
        if self.character_width_override:
            return self.character_width_override
        # ESC/POS Font A: ~32 cols on 58 mm, ~48 on 80 mm (576 dots / 12).
        return 32 if self.paper_width == "58" else 48


class MessagePrinter(Protocol):
    def print(self, message: StoredMessage, formatted_body: str, settings: PrinterSettings) -> None:
        ...

    def name(self) -> str:
        ...


class PrinterError(Exception):
    pass
