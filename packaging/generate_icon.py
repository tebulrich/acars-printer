"""Write a tiny Windows .ico for the packaged app (no Pillow required)."""

from __future__ import annotations

import struct
from pathlib import Path


def _rgba_png(width: int, height: int, rgba: bytes) -> bytes:
    import zlib

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


def write_icon(path: Path) -> None:
    size = 32
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            # Dark panel with amber accent bar — matches the app vibe enough for an icon.
            if 6 <= x <= 25 and 12 <= y <= 19:
                pixels.extend((212, 146, 58, 255))  # accent
            elif 4 <= x <= 27 and 4 <= y <= 27:
                pixels.extend((28, 32, 38, 255))
            else:
                pixels.extend((0, 0, 0, 0))
    png = _rgba_png(size, size, bytes(pixels))
    # ICONDIR + one ICONDIRENTRY pointing at PNG data (Vista+ ICO).
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack(
        "<BBBBHHII",
        size,
        size,
        0,
        0,
        1,
        32,
        len(png),
        6 + 16,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entry + png)


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "acars-bridge.ico"
    write_icon(out)
    print(out)
