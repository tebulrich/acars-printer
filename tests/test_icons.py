from __future__ import annotations

from acars_bridge.ui.icons import icon_rgba, logo_path, make_app_icon, rgba_png, write_ico


def test_logo_asset_exists():
    assert logo_path().is_file()


def test_icon_rgba_size():
    raw = icon_rgba(32)
    assert len(raw) == 32 * 32 * 4
    # Full-bleed brand mark — center pixel should be opaque.
    mid = ((16 * 32 + 16) * 4) + 3
    assert raw[mid] == 255


def test_png_and_ico_roundtrip(tmp_path):
    png = rgba_png(16, 16, icon_rgba(16))
    assert png.startswith(b"\x89PNG")
    ico = tmp_path / "t.ico"
    write_ico(ico, sizes=(16, 32))
    data = ico.read_bytes()
    assert data[:4] == b"\x00\x00\x01\x00"
    assert ico.stat().st_size > 100


def test_make_app_icon_non_null():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    icon = make_app_icon()
    assert not icon.isNull()
    assert icon.availableSizes()
    assert app is not None


def test_make_brand_pixmap():
    from PySide6.QtWidgets import QApplication

    from acars_bridge.ui.icons import make_brand_pixmap

    _app = QApplication.instance() or QApplication([])
    pix = make_brand_pixmap(36)
    assert not pix.isNull()
    assert pix.width() == 36
    assert pix.height() == 36
