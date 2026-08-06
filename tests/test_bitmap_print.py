from __future__ import annotations

from acars_bridge.printing.base import PrinterSettings
from acars_bridge.printing.bitmap_render import (
    columns_for_bitmap,
    edge_inset_dots,
    load_glyph_font,
    measure_char_width,
    mm_hint,
    paper_dot_width,
    px_to_mm,
    render_receipt_bitmap,
    usable_dot_width,
)
from acars_bridge.printing.escpos_printer import EscPosMessagePrinter
from acars_bridge.models.messages import StoredMessage


def test_px_to_mm_203dpi():
    assert px_to_mm(8) == 1.0
    assert "1.0 mm" in mm_hint(8)
    assert paper_dot_width("80") == 576
    assert paper_dot_width("58") == 384
    assert edge_inset_dots() == 16
    assert usable_dot_width("80") == 576 - 32


def test_bitmap_columns_fit_usable_width():
    glyph_px = 28
    cols = columns_for_bitmap("80", glyph_px)
    assert 24 <= cols <= 64
    char_w = measure_char_width(load_glyph_font(glyph_px))
    assert cols * char_w <= usable_dot_width("80")


def test_render_receipt_bitmap_size():
    img = render_receipt_bitmap(
        "ACARS BEGIN\nHELLO\nACARS END\n",
        paper_width="80",
        glyph_px=20,
        line_gap_px=2,
        bold=True,
    )
    assert img.mode == "1"
    assert img.size[0] == 576
    assert img.size[1] > 40


def test_escpos_bitmap_writes_raster(tmp_path):
    path = tmp_path / "bmp.bin"
    settings = PrinterSettings(
        destination=f"file://{path}",
        paper_width="80",
        render_mode="bitmap",
        glyph_px=18,
        cut_enabled=False,
    )
    msg = StoredMessage(
        id=1,
        fingerprint="x",
        direction="in",
        callsign="DLH4MC",
        sender="EDDF_DEL",
        recipient="DLH4MC",
        to_station=None,
        message_type="telex",
        raw_payload="x",
        normalized_body="TEST",
        min=None,
        mrn=None,
        ra=None,
        send_status=None,
        received_at="2026-08-04T18:09:00+00:00",
    )
    EscPosMessagePrinter().print(msg, "ACARS BEGIN\nTEST LINE\nACARS END\n", settings)
    data = path.read_bytes()
    assert len(data) > 100
    # Raster / bit-image commands typically include GS v 0 (0x1d 0x76 0x30)
    # or ESC * — either proves we did not only send plain text.
    assert b"\x1dv0" in data or b"\x1d\x76\x30" in data or b"\x1b*" in data
