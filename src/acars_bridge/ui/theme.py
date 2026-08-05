from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from acars_bridge.ui.system_fonts import preferred_mono_font, preferred_ui_font

COLORS = {
    "bg": "#12161c",
    "panel": "#1a212b",
    "panel_alt": "#222b38",
    "border": "#2f3b4d",
    "text": "#e8eef7",
    "muted": "#9aa8bc",
    "accent": "#3dd6c6",
    "accent_dim": "#2a9d8f",
    "warn": "#f4a261",
    "danger": "#e76f51",
    "ok": "#80ed99",
}


def app_stylesheet() -> str:
    c = COLORS
    return f"""
    QWidget {{
        background-color: {c["bg"]};
        color: {c["text"]};
        font-size: 14px;
    }}
    QMainWindow, QDialog {{
        background-color: {c["bg"]};
    }}
    QFrame#Header, QFrame#Compose, QFrame#Panel, QFrame#Detail, QFrame#SettingsFooter {{
        background-color: {c["panel"]};
        border: none;
    }}
    QFrame#SettingsFooter {{
        border-top: 1px solid {c["border"]};
    }}
    QLabel#Chip {{
        background-color: {c["panel_alt"]};
        border: 1px solid {c["border"]};
        border-radius: 6px;
        padding: 6px 10px;
        color: {c["text"]};
    }}
    QLabel#Brand {{
        font-size: 20px;
        font-weight: 700;
        color: {c["text"]};
    }}
    QLabel#Subtitle, QLabel#Muted, QLabel#Toast {{
        color: {c["muted"]};
        font-size: 13px;
    }}
    QLabel#Toast[error="true"] {{
        color: {c["danger"]};
    }}
    QLabel#Toast[error="false"] {{
        color: {c["ok"]};
    }}
    QLabel#Title {{
        font-size: 16px;
        font-weight: 700;
    }}
    QPushButton {{
        background-color: {c["panel_alt"]};
        color: {c["text"]};
        border: 1px solid {c["border"]};
        border-radius: 6px;
        padding: 8px 14px;
        min-height: 36px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {c["border"]};
    }}
    QPushButton:pressed {{
        background-color: {c["accent_dim"]};
    }}
    QPushButton:disabled {{
        background-color: {c["panel"]};
        color: {c["muted"]};
        border: 1px solid {c["border"]};
    }}
    QPushButton#Primary {{
        background-color: {c["accent_dim"]};
        border: 1px solid {c["accent_dim"]};
        color: {c["bg"]};
    }}
    QPushButton#Primary:hover {{
        background-color: {c["accent"]};
        border: 1px solid {c["accent"]};
    }}
    QPushButton#Primary:disabled {{
        background-color: {c["panel"]};
        border: 1px solid {c["border"]};
        color: {c["muted"]};
    }}
    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
        background-color: {c["panel_alt"]};
        color: {c["text"]};
        border: 1px solid {c["border"]};
        border-radius: 6px;
        padding: 8px 10px;
        min-height: 36px;
        selection-background-color: {c["accent_dim"]};
        selection-color: {c["bg"]};
    }}
    QSpinBox {{
        padding-right: 4px;
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        background-color: {c["border"]};
        border: none;
        width: 32px;
        subcontrol-origin: border;
    }}
    QSpinBox::up-button {{
        subcontrol-position: top right;
        margin: 1px 1px 0 0;
        border-top-right-radius: 5px;
    }}
    QSpinBox::down-button {{
        subcontrol-position: bottom right;
        margin: 0 1px 1px 0;
        border-bottom-right-radius: 5px;
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
        background-color: {c["accent_dim"]};
    }}
    QSpinBox::up-arrow, QSpinBox::down-arrow {{
        width: 12px;
        height: 12px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 28px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {c["panel"]};
        color: {c["text"]};
        border: 1px solid {c["border"]};
        selection-background-color: {c["accent_dim"]};
    }}
    QTabWidget::pane {{
        border: 1px solid {c["border"]};
        background: {c["panel"]};
        border-radius: 8px;
        top: -1px;
    }}
    QTabBar::tab {{
        background: {c["panel_alt"]};
        color: {c["muted"]};
        border: 1px solid {c["border"]};
        border-bottom: none;
        padding: 8px 16px;
        margin-right: 4px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
    }}
    QTabBar::tab:selected {{
        background: {c["panel"]};
        color: {c["text"]};
        font-weight: 700;
    }}
    QScrollArea, QListWidget, QAbstractScrollArea {{
        background: {c["panel_alt"]};
        border: 1px solid {c["border"]};
        border-radius: 8px;
    }}
    QListWidget::item {{
        padding: 6px 8px;
    }}
    QListWidget::item:selected {{
        background: {c["border"]};
        color: {c["text"]};
    }}
    QStatusBar {{
        background: {c["panel"]};
        color: {c["muted"]};
    }}
    """


def apply_theme(app: QApplication, *, ui_scale: float = 1.0) -> None:
    """Apply cockpit QSS + OS UI font. Qt handles DPI natively."""
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())

    ui_family = _first_available_family(
        preferred_ui_font().family,
        "Segoe UI",
        "Helvetica Neue",
        "Ubuntu",
        "Noto Sans",
        "DejaVu Sans",
        "Sans Serif",
    )
    mono_family = _first_available_family(
        preferred_mono_font().family,
        "JetBrains Mono",
        "Cascadia Mono",
        "Menlo",
        "Consolas",
        "DejaVu Sans Mono",
        "Monospace",
    )

    scale = max(0.85, min(1.5, float(ui_scale)))
    point_size = max(10, int(round(11 * scale)))
    font = QFont(ui_family, point_size)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)

    # Stash for widgets that want an explicit mono face.
    app.setProperty("acarsMonoFamily", mono_family)
    app.setProperty("acarsUiFamily", ui_family)


def mono_font(point_size: int | None = None) -> QFont:
    app = QApplication.instance()
    family = "monospace"
    if app is not None:
        family = str(app.property("acarsMonoFamily") or family)
    size = point_size or (app.font().pointSize() if app else 11)
    return QFont(family, size)


def _first_available_family(*candidates: str) -> str:
    available = set(QFontDatabase.families())
    for name in candidates:
        if name in available:
            return name
        # Case-insensitive match (Jetbrains vs JetBrains)
        for fam in available:
            if fam.lower() == name.lower():
                return fam
    return candidates[-1]
