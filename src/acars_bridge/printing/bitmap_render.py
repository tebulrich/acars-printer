"""Exact-size thermal text via 1-bit bitmap (ESC/POS image).

Built-in Font A/B cells are fixed (~24 / ~17 dots). Multipliers only go
larger. For ~1 mm tweaks, render monospace glyphs at a chosen pixel height
and send a raster — at 203 dpi, 8 px ≈ 1 mm.
"""

from __future__ import annotations

import math
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

# Typical 203 dpi POS heads: 576 dots @ 80 mm, 384 @ 58 mm.
_DOTS_58 = 384
_DOTS_80 = 576
_DPI = 203
# Keep content inside the printable area (heads often clip the outer ~1–2 mm).
# ≈ 1.5 mm @ 203 dpi — one millimetre more usable width than a 2 mm inset.
_EDGE_INSET_DOTS = 12


def paper_dot_width(paper_width: str) -> int:
    return _DOTS_58 if str(paper_width) == "58" else _DOTS_80


def edge_inset_dots() -> int:
    return _EDGE_INSET_DOTS


def usable_dot_width(paper_width: str) -> int:
    return max(64, paper_dot_width(paper_width) - 2 * _EDGE_INSET_DOTS)


def px_to_mm(px: int, *, dpi: int = _DPI) -> float:
    return round(px * 25.4 / dpi, 2)


def mm_hint(px: int) -> str:
    return f"≈ {px_to_mm(px):.1f} mm @ 203 dpi"


@lru_cache(maxsize=8)
def _mono_font_path() -> str | None:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [
        os.path.join(windir, "Fonts", "consola.ttf"),
        os.path.join(windir, "Fonts", "consolab.ttf"),
        os.path.join(windir, "Fonts", "cour.ttf"),
        os.path.join(windir, "Fonts", "lucon.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def load_glyph_font(size_px: int, *, bold: bool = False) -> ImageFont.ImageFont:
    size = max(8, min(96, int(size_px)))
    path = _mono_font_path()
    if path:
        # Prefer the bold face when available.
        if bold:
            bold_path = path.replace("consola.ttf", "consolab.ttf").replace(
                "cour.ttf", "courbd.ttf"
            )
            if bold_path != path and os.path.isfile(bold_path):
                path = bold_path
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def measure_char_width(font: ImageFont.ImageFont) -> int:
    """Advance width of a typical monospace glyph ('M').

    Prefer advance (getlength) over ink bbox — bbox is often narrower and
    causes too many columns, so full-width lines spill past the paper edge.
    """
    try:
        advance = float(font.getlength("M"))  # type: ignore[attr-defined]
        if advance > 0:
            return max(4, int(math.ceil(advance)))
    except Exception:  # noqa: BLE001
        pass
    try:
        bbox = font.getbbox("M")
        w = int(math.ceil(bbox[2] - bbox[0]))
        if w > 0:
            return max(4, w)
    except Exception:  # noqa: BLE001
        pass
    return max(6, getattr(font, "size", 12) // 2)


def columns_for_bitmap(paper_width: str, glyph_px: int, *, bold: bool = False) -> int:
    usable = usable_dot_width(paper_width)
    font = load_glyph_font(glyph_px, bold=bold)
    char_w = measure_char_width(font)
    cols = max(16, usable // char_w)
    while cols > 16 and cols * char_w > usable:
        cols -= 1
    return cols


def render_receipt_bitmap(
    text: str,
    *,
    paper_width: str,
    glyph_px: int,
    line_gap_px: int = 2,
    bold: bool = False,
) -> Image.Image:
    """Render uppercase receipt text to a 1-bit image the full paper width."""
    dots = paper_dot_width(paper_width)
    inset = _EDGE_INSET_DOTS
    font = load_glyph_font(glyph_px, bold=bold)
    gap = max(0, min(32, int(line_gap_px)))
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    if not lines:
        lines = [""]

    # Line box height from font metrics (ascent+descent), not just glyph_px.
    try:
        ascent, descent = font.getmetrics()
        line_h = max(glyph_px, int(ascent + descent))
    except Exception:  # noqa: BLE001
        line_h = glyph_px

    height = max(1, len(lines) * line_h + max(0, len(lines) - 1) * gap)
    img = Image.new("1", (dots, height), color=1)  # 1 = white on thermal
    draw = ImageDraw.Draw(img)
    y = 0
    for line in lines:
        # 0 = black dots on thermal when inverted later / mode 1.
        draw.text((inset, y), line, font=font, fill=0)
        y += line_h + gap
    return img
