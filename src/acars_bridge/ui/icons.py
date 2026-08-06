"""App / tray icon — plane + datalink print mark from packaged PNG."""

from __future__ import annotations

import struct
import zlib
from functools import lru_cache
from pathlib import Path


_LOGO_NAME = "app-logo.png"
_ICON_SIZES = (16, 20, 24, 32, 48, 64, 128, 256)


def logo_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / _LOGO_NAME


@lru_cache(maxsize=16)
def icon_rgba(size: int) -> bytes:
    """RGBA pixels for a square icon, scaled from the brand logo."""
    from PIL import Image

    path = logo_path()
    if not path.is_file():
        raise FileNotFoundError(f"App logo missing: {path}")
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        if rgba.size != (size, size):
            rgba = rgba.resize((size, size), Image.Resampling.LANCZOS)
        return rgba.tobytes()


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


def make_brand_pixmap(size: int = 36):
    """Header mark next to the product name."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap

    pix = QPixmap(str(logo_path()))
    if pix.isNull():
        return QPixmap()
    return pix.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
