from __future__ import annotations

from PySide6.QtWidgets import QApplication


def test_ui_modules_import(qapp):
    from acars_bridge.ui import run_app
    from acars_bridge.ui.app import AcarsBridgeApp
    from acars_bridge.ui.theme import apply_theme

    assert callable(run_app)
    assert AcarsBridgeApp is not None
    assert isinstance(qapp, QApplication)
    apply_theme(qapp)


def test_minimize_hides_to_tray_close_does_not():
    from acars_bridge.ui.app import hide_to_tray_on_minimize

    assert hide_to_tray_on_minimize(closing=False, minimized=True) is True
    assert hide_to_tray_on_minimize(closing=True, minimized=True) is False
    assert hide_to_tray_on_minimize(closing=False, minimized=False) is False
