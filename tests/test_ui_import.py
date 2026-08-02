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
