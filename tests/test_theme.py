from __future__ import annotations

from acars_bridge.ui.theme import COLORS, app_stylesheet, apply_theme


def test_stylesheet_covers_buttons_without_canvas_hacks():
    css = app_stylesheet()
    assert "QPushButton" in css
    assert COLORS["accent"] in css
    assert "border-radius" in css


def test_apply_theme_sets_fusion_and_font(qapp):
    apply_theme(qapp)
    assert qapp.style() is not None
    assert qapp.styleSheet()
    assert "QPushButton" in qapp.styleSheet()
    assert qapp.font().pointSize() >= 10
    from PySide6.QtWidgets import QStyle

    assert (
        qapp.style().styleHint(QStyle.StyleHint.SH_ToolTip_WakeUpDelay) == 200
    )
