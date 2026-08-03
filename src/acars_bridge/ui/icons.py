"""App / tray icon — simple dark panel with a teal print strip (no image assets)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


# Match ui/theme.py accents without importing Qt here (used by packaging too).
_PANEL = (26, 33, 43, 255)  # #1a212b
_TEAL = (61, 214, 198, 255)  # #3dd6c6
_AMBER = (244, 162, 97, 255)  # #f4a261
_CLEAR = (0, 0, 0, 0)


def icon_rgba(size: int) -> bytes:
    """RGBA pixels for a square icon: rounded dark tile + receipt lines."""
    pixels = bytearray(size * size * 4)
    margin = max(1, size // 16)
    radius = max(2, size // 6)
    # Receipt strip geometry (relative).
    strip_left = size * 28 // 100
    strip_right = size * 72 // 100
    strip_top = size * 22 // 100
    strip_bottom = size * 78 // 100
    line_count = 4 if size >= 24 else 3
    gap = max(1, (strip_bottom - strip_top) // (line_count * 2))
    line_h = max(1, size // 16)
    accent_y0 = size * 78 // 100
    accent_y1 = size * 86 // 100

    def put(x: int, y: int, rgba: tuple[int, int, int, int]) -> None:
        i = (y * size + x) * 4
        pixels[i : i + 4] = bytes(rgba)

    def inside_rounded(x: int, y: int) -> bool:
        if not (margin <= x < size - margin and margin <= y < size - margin):
            return False
        # Squircle corners via distance to nearest inner corner.
        ix0, iy0 = margin + radius, margin + radius
        ix1, iy1 = size - margin - radius - 1, size - margin - radius - 1
        cx = min(max(x, ix0), ix1)
        cy = min(max(y, iy0), iy1)
        if x < ix0 and y < iy0:
            return (x - ix0) ** 2 + (y - iy0) ** 2 <= radius * radius
        if x > ix1 and y < iy0:
            return (x - ix1) ** 2 + (y - iy0) ** 2 <= radius * radius
        if x < ix0 and y > iy1:
            return (x - ix0) ** 2 + (y - iy1) ** 2 <= radius * radius
        if x > ix1 and y > iy1:
            return (x - ix1) ** 2 + (y - iy1) ** 2 <= radius * radius
        return True

    for y in range(size):
        for x in range(size):
            if not inside_rounded(x, y):
                put(x, y, _CLEAR)
                continue
            # Amber footer tick (printer head / status).
            if accent_y0 <= y <= accent_y1 and strip_left <= x <= strip_right:
                put(x, y, _AMBER)
                continue
            # Teal receipt lines.
            painted = False
            for n in range(line_count):
                ly = strip_top + n * (line_h + gap)
                if ly <= y < ly + line_h and strip_left <= x <= strip_right:
                    # Slightly shorter alternating lines (looks like text).
                    inset = (n % 2) * max(1, (strip_right - strip_left) // 8)
                    if strip_left + inset <= x <= strip_right - inset:
                        put(x, y, _TEAL)
                        painted = True
                        break
            if not painted:
                put(x, y, _PANEL)
    return bytes(pixels)


def rgba_png(width: int, height: int, rgba: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b""
    for y in range(height):
        raw += b"\x00"
        row = y * width * 4
        raw += rgba[row : row + width * 4]
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(raw, 9)),
            chunk(b"IEND", b""),
        ]
    )


def write_ico(path: Path, sizes: tuple[int, ...] = (16, 32, 48, 256)) -> None:
    """Multi-size PNG-in-ICO for the Windows exe / shell."""
    images = [(s, rgba_png(s, s, icon_rgba(s))) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = bytearray()
    payload = bytearray()
    offset = 6 + 16 * len(images)
    for size, png in images:
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0,
            0,
            1,
            32,
            len(png),
            offset,
        )
        payload += png
        offset += len(png)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + payload)


def make_app_icon():
    """QIcon with several sizes for window + system tray."""
    from PySide6.QtGui import QIcon, QPixmap

    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        png = rgba_png(size, size, icon_rgba(size))
        pix = QPixmap()
        if pix.loadFromData(png, "PNG"):
            icon.addPixmap(pix)
    return icon
