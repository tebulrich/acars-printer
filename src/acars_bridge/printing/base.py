from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from acars_bridge.models.messages import StoredMessage

PrintFont = Literal["a", "b"]
PrintRenderMode = Literal["native", "bitmap"]


@dataclass(frozen=True, slots=True)
class PrinterSettings:
    destination: str
    paper_width: str = "80"
    cut_enabled: bool = True
    character_width_override: int | None = None
    aircraft_registration: str | None = None
    # Thermal style (tunable in Settings — printers vary).
    font: PrintFont = "a"
    bold: bool = False
    render_mode: PrintRenderMode = "native"
    # Native ESC/POS glyph scale (1–8). Built-in fonts cannot go below 1×.
    char_width: int = 1
    char_height: int = 1
    # None = printer default. Units are ESC/POS 1/180 inch (≈0.14 mm).
    line_spacing_dots: int | None = None
    # Bitmap mode: exact glyph height in printer dots (8 px ≈ 1 mm @ 203 dpi).
    glyph_px: int = 28
    line_gap_px: int = 2
    lead_in_lines: int = 2
    tear_feed_lines: int = 6
    pairing_url: str | None = None

    def characters_per_line(self) -> int:
        if self.character_width_override:
            cols = self.character_width_override
        elif self.render_mode == "bitmap":
            from acars_bridge.printing.bitmap_render import columns_for_bitmap

            cols = columns_for_bitmap(self.paper_width, self.glyph_px, bold=self.bold)
        elif self.font == "b":
            # ESC/POS Font B: ~42 cols on 58 mm, ~64 on 80 mm.
            cols = 42 if self.paper_width == "58" else 64
        else:
            # ESC/POS Font A: ~32 cols on 58 mm, ~48 on 80 mm (576 dots / 12).
            cols = 32 if self.paper_width == "58" else 48
        # Native double-width (or width>1) uses multiple cells per glyph.
        if self.render_mode == "native" and self.char_width > 1:
            cols = max(16, cols // self.char_width)
        return cols


class MessagePrinter(Protocol):
    def print(self, message: StoredMessage, formatted_body: str, settings: PrinterSettings) -> None:
        ...

    def name(self) -> str:
        ...


class PrinterError(Exception):
    pass
