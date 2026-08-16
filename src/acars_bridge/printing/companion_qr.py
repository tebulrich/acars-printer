"""Pairing QR for the LAN phone companion (first flight-plan of each OFP lock)."""

from __future__ import annotations

import base64
import io

from PIL import Image


PAIRING_QR_TICKET = "flight_plan"


def should_emit_pairing_qr(
    *,
    enabled: bool,
    url: str,
    already: bool,
    ticket_type: str = "",
) -> bool:
    """QR only on the SimBrief flight-plan strip (the one with the route)."""
    return bool(
        enabled
        and (url or "").strip()
        and not already
        and ticket_type.strip().lower() == PAIRING_QR_TICKET
    )


def pairing_caption(url: str) -> str:
    cleaned = (url or "").strip()
    return f"PHONE INBOX\nSCAN TO OPEN\n{cleaned}"


def qr_bitmap(url: str, *, scale: int = 5, border: int = 2) -> Image.Image:
    import segno

    qr = segno.make((url or "").strip() or "http://127.0.0.1/", error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=max(2, int(scale)), border=max(1, int(border)))
    buf.seek(0)
    img = Image.open(buf)
    if img.mode != "1":
        img = img.convert("1")
    return img


def pairing_png_base64(url: str) -> str:
    img = qr_bitmap(url, scale=5, border=2)
    buf = io.BytesIO()
    img.convert("L").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def stack_pairing_qr(receipt: Image.Image, url: str, paper_width: str) -> Image.Image:
    from acars_bridge.printing.bitmap_render import paper_dot_width

    dots = paper_dot_width(paper_width)
    qr = qr_bitmap(url, scale=6, border=2)
    target = max(96, min(dots - 16, (dots * 45) // 100))
    if qr.size[0] != target:
        qr = qr.resize((target, target), Image.Resampling.NEAREST).convert("1")
    gap = 10
    out = Image.new("1", (dots, receipt.height + gap + qr.height + 8), color=1)
    if receipt.size[0] == dots:
        out.paste(receipt, (0, 0))
    else:
        out.paste(receipt, (0, 0))
    x = max(0, (dots - qr.size[0]) // 2)
    out.paste(qr, (x, receipt.height + gap))
    return out
