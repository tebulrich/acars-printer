from __future__ import annotations

from acars_bridge.ui.theme import COLORS, app_stylesheet, apply_theme


def test_stylesheet_covers_buttons_without_canvas_hacks():
    css = app_stylesheet()
    assert "QPushButton" in css
    assert COLORS["accent"] in css
    assert "border-radius" in css


def test_apply_theme_sets_fusion_and_font(qapp):
    apply_theme(qapp, ui_scale=1.0)
    assert qapp.style() is not None
    assert qapp.styleSheet()
    assert "QPushButton" in qapp.styleSheet()
    assert qapp.font().pointSize() >= 10
