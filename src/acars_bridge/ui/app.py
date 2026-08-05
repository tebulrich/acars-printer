from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QGuiApplication, QTextOption
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from acars_bridge import __version__
from acars_bridge.config import AppPaths
from acars_bridge.hoppie.types import MessageType
from acars_bridge.models.messages import StoredMessage
from acars_bridge.printing.base import PrinterSettings
from acars_bridge.printing.discovery import (
    destination_from_label,
    label_for_destination,
    list_printer_choices,
)
from acars_bridge.services.debug_log import DebugLog
from acars_bridge.services.session import AppSession, build_session
from acars_bridge.tap.service import TapService, TapStatus
from acars_bridge.ui.icons import make_app_icon
from acars_bridge.ui.notifications import notify
from acars_bridge.ui.theme import COLORS, apply_theme, mono_font
from acars_bridge.ui.updates import UpdateController


class _TapBridge(QObject):
    """Marshal tap callbacks onto the Qt UI thread."""

    updated = Signal(object)
    new_messages = Signal(int)


class AcarsBridgeApp(QMainWindow):
    def __init__(self, session: AppSession) -> None:
        super().__init__()
        self.session = session
        self._selected_id: int | None = None
        self._message_ids: list[int] = []
        self._closing = False
        self._quit_requested = False
        self._tray: QSystemTrayIcon | None = None
        self._printer_choices = list_printer_choices(session.settings.printer_destination())
        self._format_widgets: dict[str, Any] = {}
        self._settings_widgets: dict[str, Any] = {}

        self.setWindowTitle(f"ACARS Print Bridge  ·  {__version__}")
        self.setMinimumSize(720, 520)
        self.resize(900, 600)
        self._app_icon = make_app_icon()
        self.setWindowIcon(self._app_icon)
        # Detail pane: hidden while auto-print is on until the user opens a message.
        self._detail_opened = False

        # Messages are session-scoped in the UI — don't keep yesterday's list.
        self.session.messages.clear_all()

        self._bridge = _TapBridge(self)
        self._bridge.updated.connect(self._apply_tap_update)
        self._bridge.new_messages.connect(self._on_new_messages)

        self.debug = DebugLog(
            session.paths.root / "debug.log",
            get_logon=session.settings.hoppie_logon,
        )

        self.tap = TapService(
            session,
            on_update=lambda status: self._bridge.updated.emit(status),
            on_new_messages=lambda count: self._bridge.new_messages.emit(count),
            on_debug=lambda msg: self.debug.info("tap_dbg", message=msg),
        )

        self.debug.info("app_ready", version=__version__, **self._debug_context())

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._clear_toast)
        self._user_check_pending = False

        self._build_ui()
        self._setup_tray()
        self._refresh_header()
        self._reload_messages()
        self._set_link_state("off")

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self._tick_clock()

        # After the window is up — same path as the Connect button.
        if self.session.settings.auto_connect():
            QTimer.singleShot(400, self._maybe_auto_connect)

        self._updates = UpdateController(self, session)
        if self.session.settings.check_updates():
            QTimer.singleShot(2500, lambda: self._updates.check(manual=False))

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_body(), stretch=1)

        self.toast = QLabel("")
        self.toast.setObjectName("Toast")
        self.toast.setProperty("error", False)
        self.toast.setContentsMargins(14, 8, 14, 10)
        self.toast.setVisible(False)
        layout.addWidget(self.toast)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        row = QHBoxLayout(header)
        row.setContentsMargins(18, 14, 16, 14)

        brand_col = QVBoxLayout()
        brand = QLabel("ACARS PRINT BRIDGE")
        brand.setObjectName("Brand")
        self.subtitle = QLabel("Print bridge · copies what your aircraft gets from Hoppie")
        self.subtitle.setObjectName("Subtitle")
        brand_col.addWidget(brand)
        brand_col.addWidget(self.subtitle)
        row.addLayout(brand_col)
        row.addStretch(1)

        self.callsign_chip = self._chip("FLT —")
        self.link_chip = self._chip("LINK off")
        self.clock_chip = self._chip("UTC —")
        for chip in (self.callsign_chip, self.link_chip, self.clock_chip):
            row.addWidget(chip)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setObjectName("Primary")
        self.btn_connect.clicked.connect(
            lambda: self._run_action("start", self._start_tap)
        )
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.clicked.connect(
            lambda: self._run_action("pause", self._stop_tap)
        )
        self.btn_debug = QPushButton("Debug")
        self.btn_debug.clicked.connect(self._show_debug_log)
        self.btn_quit = QPushButton("Quit")
        self.btn_quit.setToolTip("Exit completely (stops the Hoppie tap)")
        self.btn_quit.clicked.connect(self._quit_app)
        for btn in (
            self.btn_connect,
            self.btn_disconnect,
            self.btn_debug,
            self.btn_quit,
        ):
            row.addWidget(btn)
        self._sync_connection_buttons(running=False)
        return header

    def _build_body(self) -> QWidget:
        body = QWidget()
        row = QHBoxLayout(body)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(10)

        self.tabs = QTabWidget()
        self.tab_messages = QWidget()
        self.tab_format = QWidget()
        self.tab_settings = QWidget()
        self.tabs.addTab(self.tab_messages, "Messages")
        self.tabs.addTab(self.tab_format, "Format")
        self.tabs.addTab(self.tab_settings, "Settings")
        self._build_messages_tab()
        self._build_format_tab()
        self._build_settings_tab()
        self._body_row = row
        self._tabs_stretch = 1
        row.addWidget(self.tabs, stretch=self._tabs_stretch)
        self.detail_panel = self._build_detail()
        row.addWidget(self.detail_panel, stretch=2)
        self._sync_detail_visibility()
        return body

    def _build_messages_tab(self) -> None:
        layout = QVBoxLayout(self.tab_messages)
        layout.setContentsMargins(10, 10, 10, 10)
        head = QHBoxLayout()
        title = QLabel("Traffic")
        title.setObjectName("Title")
        head.addWidget(title)
        head.addStretch(1)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setToolTip("Reload message list and bridge status")
        self.btn_refresh.clicked.connect(
            lambda: self._run_action("refresh", self._refresh)
        )
        head.addWidget(self.btn_refresh)
        layout.addLayout(head)

        note = QLabel(
            "Connect as Administrator, then keep flying. "
            "Tune strip look on the Format tab (Save and test print). "
            "With auto-print on, open a row to inspect it."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.message_list = QListWidget()
        self.message_list.itemSelectionChanged.connect(self._on_list_selection)
        layout.addWidget(self.message_list, stretch=1)

    def _build_detail(self) -> QWidget:
        detail = QFrame()
        detail.setObjectName("Detail")
        layout = QVBoxLayout(detail)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        self.detail_title = QLabel("Select a message")
        self.detail_title.setObjectName("Title")
        title_row.addWidget(self.detail_title, stretch=1)
        self.btn_hide_detail = QPushButton("Hide")
        self.btn_hide_detail.setToolTip("Collapse message details")
        self.btn_hide_detail.clicked.connect(self._hide_detail)
        title_row.addWidget(self.btn_hide_detail)
        layout.addLayout(title_row)

        self.detail_meta = QLabel("New traffic from your aircraft client appears here and prints.")
        self.detail_meta.setObjectName("Muted")
        self.detail_meta.setWordWrap(True)
        layout.addWidget(self.detail_meta)

        self.detail_body = QPlainTextEdit()
        self.detail_body.setReadOnly(True)
        self.detail_body.setFont(mono_font())
        self.detail_body.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        layout.addWidget(self.detail_body, stretch=1)

        action_row = QHBoxLayout()
        self.btn_print = QPushButton("Print")
        self.btn_print.setObjectName("Primary")
        self.btn_print.clicked.connect(lambda: self._run_action("reprint", self._reprint))
        self.btn_print.setEnabled(False)
        action_row.addWidget(self.btn_print)
        action_row.addStretch(1)
        layout.addLayout(action_row)
        return detail

    def _build_format_tab(self) -> None:
        """Strip appearance + Test print — tweak and print without leaving this tab."""
        outer = QVBoxLayout(self.tab_format)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setContentsMargins(16, 16, 16, 12)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        registration = QLineEdit(self.session.settings.aircraft_registration() or "")
        registration.setPlaceholderText("optional — e.g. D-AILA (omit if empty)")

        printer = QComboBox()
        labels = [c.label for c in self._printer_choices]
        printer.addItems(labels)
        current = label_for_destination(self.session.settings.printer_destination())
        if current in labels:
            printer.setCurrentText(current)

        width = QComboBox()
        width.addItem("80 mm", "80")
        width.addItem("58 mm", "58")
        width_idx = width.findData(self.session.settings.paper_width())
        if width_idx >= 0:
            width.setCurrentIndex(width_idx)

        cut = QComboBox()
        cut.addItems(["on", "off"])
        cut.setCurrentText("on" if self.session.settings.cut_enabled() else "off")

        print_mode = QComboBox()
        print_mode.addItem("Exact size — set text height in mm/px", "bitmap")
        print_mode.addItem("Printer built-in font (fixed sizes only)", "native")
        mode_idx = print_mode.findData(self.session.settings.print_render_mode())
        if mode_idx >= 0:
            print_mode.setCurrentIndex(mode_idx)

        from acars_bridge.printing.bitmap_render import mm_hint

        print_glyph_px = QSpinBox()
        print_glyph_px.setRange(8, 64)
        print_glyph_px.setSuffix(" px")
        print_glyph_px.setValue(self.session.settings.print_glyph_px())
        print_glyph_px.setToolTip(
            "How tall each letter is on the paper, in printer dots. "
            "At 203 dpi, 8 dots ≈ 1 mm. Lower this if the text looks too big."
        )
        glyph_hint = QLabel(mm_hint(print_glyph_px.value()))
        glyph_hint.setObjectName("Muted")
        print_glyph_px.valueChanged.connect(
            lambda value: glyph_hint.setText(mm_hint(value))
        )

        print_line_gap = QSpinBox()
        print_line_gap.setRange(0, 32)
        print_line_gap.setSuffix(" px")
        print_line_gap.setValue(self.session.settings.print_line_gap_px())
        print_line_gap.setToolTip("Extra blank space between lines of text.")

        print_font = QComboBox()
        print_font.addItem("Font A (standard ~24 px)", "a")
        print_font.addItem("Font B (narrow ~17 px)", "b")
        font_idx = print_font.findData(self.session.settings.print_font())
        if font_idx >= 0:
            print_font.setCurrentIndex(font_idx)

        print_char_w = QSpinBox()
        print_char_w.setRange(1, 8)
        print_char_w.setPrefix("× ")
        print_char_w.setValue(self.session.settings.print_char_width())
        print_char_w.setToolTip("ESC/POS width multiplier (1–8). Cannot go below 1×.")

        print_char_h = QSpinBox()
        print_char_h.setRange(1, 8)
        print_char_h.setPrefix("× ")
        print_char_h.setValue(self.session.settings.print_char_height())
        print_char_h.setToolTip("ESC/POS height multiplier (1–8). Cannot go below 1×.")

        print_bold = QComboBox()
        print_bold.addItems(["on", "off"])
        print_bold.setCurrentText("on" if self.session.settings.print_bold() else "off")

        print_columns = QComboBox()
        print_columns.addItem("Auto (paper + font)", "auto")
        for cols in (32, 40, 42, 48, 56, 64):
            print_columns.addItem(f"{cols} columns", str(cols))
        stored_cols = self.session.settings.print_columns()
        cols_key = "auto" if stored_cols is None else str(stored_cols)
        cols_idx = print_columns.findData(cols_key)
        if cols_idx >= 0:
            print_columns.setCurrentIndex(cols_idx)
        elif stored_cols is not None:
            print_columns.addItem(f"{stored_cols} columns", str(stored_cols))
            print_columns.setCurrentIndex(print_columns.count() - 1)

        print_spacing = QSpinBox()
        print_spacing.setRange(0, 255)
        print_spacing.setSpecialValueText("printer default")
        spacing_dots = self.session.settings.print_line_spacing_dots()
        print_spacing.setValue(0 if spacing_dots is None else spacing_dots)
        print_spacing.setToolTip(
            "Built-in font line pitch (1/180 inch ≈ 0.14 mm). 0 = printer default."
        )

        print_lead_in = QSpinBox()
        print_lead_in.setRange(0, 12)
        print_lead_in.setSuffix(" lines")
        print_lead_in.setValue(self.session.settings.print_lead_in())
        print_lead_in.setToolTip(
            "Blank feed before the first line. Default 2 ≈ 1.5 cm on a POS-80."
        )

        print_tear_feed = QSpinBox()
        print_tear_feed.setRange(0, 16)
        print_tear_feed.setSuffix(" lines")
        print_tear_feed.setValue(self.session.settings.print_tear_feed())

        glyph_row = QWidget()
        glyph_layout = QHBoxLayout(glyph_row)
        glyph_layout.setContentsMargins(0, 0, 0, 0)
        glyph_layout.setSpacing(10)
        glyph_layout.addWidget(print_glyph_px)
        glyph_layout.addWidget(glyph_hint, stretch=1)

        self._format_widgets = {
            "registration": registration,
            "printer": printer,
            "width": width,
            "cut": cut,
            "print_font": print_font,
            "print_mode": print_mode,
            "print_glyph_px": print_glyph_px,
            "print_line_gap": print_line_gap,
            "print_char_w": print_char_w,
            "print_char_h": print_char_h,
            "print_bold": print_bold,
            "print_columns": print_columns,
            "print_spacing": print_spacing,
            "print_lead_in": print_lead_in,
            "print_tear_feed": print_tear_feed,
            "glyph_hint": glyph_hint,
        }

        form.addRow("Aircraft registration", registration)
        form.addRow("Printer", printer)
        form.addRow("Paper width", width)
        form.addRow("Cut / tear assist", cut)
        form.addRow("Print mode", print_mode)
        form.addRow("Text height", glyph_row)
        form.addRow("Space between lines", print_line_gap)
        form.addRow("Print font (built-in)", print_font)
        form.addRow("Char width ×", print_char_w)
        form.addRow("Char height ×", print_char_h)
        form.addRow("Line spacing (dots)", print_spacing)
        form.addRow("Print bold", print_bold)
        form.addRow("Columns (wrap)", print_columns)
        form.addRow("Top margin", print_lead_in)
        form.addRow("Bottom feed", print_tear_feed)

        def _sync_print_mode_widgets() -> None:
            bitmap = str(print_mode.currentData() or "bitmap") == "bitmap"
            print_glyph_px.setEnabled(bitmap)
            glyph_hint.setEnabled(bitmap)
            print_line_gap.setEnabled(bitmap)
            print_font.setEnabled(not bitmap)
            print_char_w.setEnabled(not bitmap)
            print_char_h.setEnabled(not bitmap)
            print_spacing.setEnabled(not bitmap)

        print_mode.currentIndexChanged.connect(lambda _i: _sync_print_mode_widgets())
        _sync_print_mode_widgets()
        self._sync_format_mode_widgets = _sync_print_mode_widgets

        help_lbl = QLabel(
            "Change a value, then Save and test print. Compare with a real strip. "
            "Exact size: Text height 8 ≈ 1 mm on a typical POS-80 — if letters look "
            "~1 mm too tall, try 16–18."
        )
        help_lbl.setObjectName("Muted")
        help_lbl.setWordWrap(True)
        form.addRow(help_lbl)

        scroll.setWidget(form_host)
        outer.addWidget(scroll, stretch=1)

        footer = QFrame()
        footer.setObjectName("SettingsFooter")
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(16, 10, 16, 12)
        footer_row.setSpacing(10)
        test_btn = QPushButton("Save and test print")
        test_btn.setObjectName("Primary")
        test_btn.setToolTip("Save these format settings, then print a sample strip")
        test_btn.clicked.connect(
            lambda: self._run_action("format_test_print", self._save_format_and_test)
        )
        save_btn = QPushButton("Save format")
        save_btn.clicked.connect(
            lambda: self._run_action("save_format", self._save_format_settings)
        )
        reset_btn = QPushButton("Reset to defaults")
        reset_btn.setToolTip(
            "Restore format defaults (keeps your printer). Does not print."
        )
        reset_btn.clicked.connect(
            lambda: self._run_action("reset_format", self._reset_format_defaults)
        )
        footer_row.addWidget(test_btn)
        footer_row.addWidget(save_btn)
        footer_row.addWidget(reset_btn)
        footer_row.addStretch(1)
        outer.addWidget(footer)

    def _build_settings_tab(self) -> None:
        outer = QVBoxLayout(self.tab_settings)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setContentsMargins(16, 16, 16, 12)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        callsign = QLineEdit(self.session.settings.callsign() or "")
        callsign.setPlaceholderText("optional — only print this flight")

        logon = QLineEdit()
        logon.setEchoMode(QLineEdit.EchoMode.Password)
        logon.setPlaceholderText(
            "stored — leave blank to keep"
            if self.session.settings.hoppie_logon()
            else "Hoppie ACARS logon code (not your Windows user)"
        )

        auto_print = QComboBox()
        auto_print.addItems(["on", "off"])
        auto_print.setCurrentText("on" if self.session.settings.auto_print() else "off")

        auto_connect = QComboBox()
        auto_connect.addItems(["on", "off"])
        auto_connect.setCurrentText(
            "on" if self.session.settings.auto_connect() else "off"
        )

        check_updates = QComboBox()
        check_updates.addItems(["on", "off"])
        check_updates.setCurrentText(
            "on" if self.session.settings.check_updates() else "off"
        )

        ui_scale = QComboBox()
        ui_scale.addItems(["85%", "100%", "115%", "125%"])
        scale = self.session.settings.ui_scale()
        nearest = min(
            [(0.85, "85%"), (1.0, "100%"), (1.15, "115%"), (1.25, "125%")],
            key=lambda item: abs(item[0] - scale),
        )[1]
        ui_scale.setCurrentText(nearest)

        self._settings_widgets = {
            "callsign": callsign,
            "logon": logon,
            "auto_print": auto_print,
            "auto_connect": auto_connect,
            "check_updates": check_updates,
            "ui_scale": ui_scale,
        }

        form.addRow("Callsign filter", callsign)
        form.addRow("Hoppie logon", logon)
        form.addRow("Auto-print", auto_print)
        form.addRow("Auto-connect", auto_connect)
        form.addRow("Check for updates", check_updates)
        form.addRow("UI scale", ui_scale)

        help_lbl = QLabel(
            "Hoppie logon is the secret ACARS code from hoppie.nl (not a Windows "
            "username). Printer and strip layout live on the Format tab. Connect as "
            "Administrator to intercept; Disconnect restores normal Hoppie access."
        )
        help_lbl.setObjectName("Muted")
        help_lbl.setWordWrap(True)
        form.addRow(help_lbl)

        scroll.setWidget(form_host)
        outer.addWidget(scroll, stretch=1)

        footer = QFrame()
        footer.setObjectName("SettingsFooter")
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(16, 10, 16, 12)
        footer_row.setSpacing(10)
        save = QPushButton("Save settings")
        save.setObjectName("Primary")
        save.clicked.connect(
            lambda: self._run_action("save_settings", self._save_settings)
        )
        check_btn = QPushButton("Check for updates now")
        check_btn.clicked.connect(lambda: self._updates.check(manual=True))
        footer_row.addWidget(save)
        footer_row.addWidget(check_btn)
        footer_row.addStretch(1)
        outer.addWidget(footer)

    def _setup_tray(self) -> None:
        # Tray is a convenience only. Elevated Windows apps often lose the
        # notification icon — never rely on it for exit (X / Quit always exit).
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.debug.info("tray", available=False)
            return
        tray = QSystemTrayIcon(self._app_icon, self)
        tray.setToolTip("ACARS Print Bridge")
        menu = QMenu(self)
        show_action = QAction("Show window", self)
        show_action.triggered.connect(self._show_from_tray)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit_app)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._tray = tray
        self.debug.info("tray", available=True)

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        self._quit_app()

    def _quit_app(self) -> None:
        """Exit for real — stop tap, release lock, leave no ghost process."""
        if self._closing:
            return
        self._quit_requested = True
        self.close()

    @Slot(QSystemTrayIcon.ActivationReason)
    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_from_tray()

    def _update_tray_tooltip(self) -> None:
        if self._tray is None:
            return
        if self.tap.status.running:
            filt = self.session.settings.callsign() or "ALL"
            self._tray.setToolTip(f"ACARS Print Bridge · connected ({filt})")
        else:
            self._tray.setToolTip("ACARS Print Bridge · disconnected")

    def _chip(self, text: str) -> QLabel:
        chip = QLabel(text)
        chip.setObjectName("Chip")
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return chip

    def _refresh(self) -> None:
        """Reload the message list; if connected, also refresh bridge status."""
        self._reload_messages()
        if self.tap.status.running:
            self._user_check_pending = True
            self.tap.check_now()
        else:
            self._flash("Message list refreshed · bridge off")

    def _printer_ready(self) -> bool:
        dest = self.session.settings.printer_destination()
        return bool(dest)

    def _refresh_header(self) -> None:
        callsign = self.session.settings.callsign() or "ALL"
        self.callsign_chip.setText(f"FLT {callsign}")
        self.callsign_chip.setToolTip(
            "Callsign filter" if self.session.settings.callsign() else "Printing all flights seen"
        )

    def _reload_messages(self) -> None:
        self.message_list.blockSignals(True)
        self.message_list.clear()
        rows = self.session.messages.list_recent(80)
        self._message_ids = [msg.id for msg in rows]
        if not rows:
            if not self.tap.status.running:
                empty = (
                    "Set up first:\n"
                    "1) Settings → pick your printer\n"
                    "2) Run as Administrator → Connect\n"
                    "3) Keep flying — no plane restart needed"
                )
            else:
                empty = "Connected — waiting for plane traffic (CPDLC, telex, weather…)."
            item = QListWidgetItem(empty)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.message_list.addItem(item)
            self.message_list.blockSignals(False)
            self._selected_id = None
            self._detail_opened = False
            self._reset_detail_placeholder()
            self._sync_detail_visibility()
            return
        for msg in rows:
            self.message_list.addItem(self._message_item(msg))
        self.message_list.blockSignals(False)

        auto_print = self.session.settings.auto_print()
        if not auto_print:
            # Review mode: keep detail open and select something useful.
            self._detail_opened = True
            if self._selected_id in self._message_ids:
                self._select_message(self._selected_id)
            elif rows:
                self._select_message(rows[0].id)
        elif self._detail_opened and self._selected_id in self._message_ids:
            self._select_message(self._selected_id)
        else:
            self._selected_id = None
            self.message_list.clearSelection()
            self._detail_opened = False
            self._reset_detail_placeholder()
        self._sync_detail_visibility()

    def _message_item(self, msg: StoredMessage) -> QListWidgetItem:
        preview = msg.normalized_body.replace("\n", " ")[:48]
        direction = "OUT" if msg.direction == "out" else "IN"
        station = msg.sender or msg.to_station or "?"
        label = f"{direction}  {station}  {msg.message_type.upper()}  {preview}"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, msg.id)
        return item

    def _on_list_selection(self) -> None:
        items = self.message_list.selectedItems()
        if not items:
            return
        mid = items[0].data(Qt.ItemDataRole.UserRole)
        if isinstance(mid, int):
            self._detail_opened = True
            self._select_message(mid)
            self._sync_detail_visibility()

    def _select_message(self, message_id: int) -> None:
        self._selected_id = message_id
        msg = self.session.messages.get(message_id)
        if not msg:
            return

        for i in range(self.message_list.count()):
            item = self.message_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == message_id:
                self.message_list.blockSignals(True)
                self.message_list.setCurrentItem(item)
                self.message_list.blockSignals(False)
                break

        title_from = msg.sender if msg.direction == "in" else msg.to_station
        try:
            type_label = MessageType(msg.message_type).label()
        except ValueError:
            type_label = msg.message_type.upper()
        self.detail_title.setText(f"{type_label}  ·  {title_from or 'UNKNOWN'}")
        meta_bits = [
            "INBOUND" if msg.direction == "in" else "OUTBOUND",
            f"FLT {msg.callsign}",
            f"#{msg.id}",
        ]
        if msg.min is not None:
            meta_bits.append(f"MIN {msg.min}")
        if msg.ra:
            meta_bits.append(f"RA {msg.ra}")
        self.detail_meta.setText("  ·  ".join(meta_bits))
        self.detail_body.setPlainText(msg.normalized_body)
        self.btn_print.setEnabled(True)

    def _reset_detail_placeholder(self) -> None:
        self.detail_title.setText("Select a message")
        self.detail_meta.setText(
            "Traffic prints automatically when auto-print is on. "
            "Click a row to inspect it here."
        )
        self.detail_body.clear()
        self.btn_print.setEnabled(False)

    def _hide_detail(self) -> None:
        self._detail_opened = False
        self._selected_id = None
        self.message_list.clearSelection()
        self._reset_detail_placeholder()
        self._sync_detail_visibility()

    def _detail_should_show(self) -> bool:
        if not self.session.settings.auto_print():
            return True
        return self._detail_opened and self._selected_id is not None

    def _sync_detail_visibility(self) -> None:
        show = self._detail_should_show()
        self.detail_panel.setVisible(show)
        self.btn_hide_detail.setVisible(self.session.settings.auto_print())
        # Give the list more room when detail is collapsed.
        if hasattr(self, "_body_row"):
            self._body_row.setStretch(self._body_row.indexOf(self.tabs), 1 if show else 1)
            self._body_row.setStretch(
                self._body_row.indexOf(self.detail_panel), 2 if show else 0
            )

    def _flash(self, text: str, *, error: bool = False) -> None:
        self.toast.setText(text)
        self.toast.setProperty("error", error)
        self.toast.style().unpolish(self.toast)
        self.toast.style().polish(self.toast)
        self.toast.setVisible(True)
        self.debug.toast(text, error=error)
        self._toast_timer.start(8000 if error else 4500)

    def _clear_toast(self) -> None:
        self.toast.clear()
        self.toast.setVisible(False)

    def _debug_context(self) -> dict[str, Any]:
        settings = self.session.settings
        tap = getattr(self, "tap", None)
        return {
            "mode": "tap",
            "hoppie_type": "tap",
            "callsign": settings.callsign() or "ALL",
            "printer": settings.printer_destination(),
            "running": tap is not None and tap.status.running,
            "exchanges": tap.status.exchanges if tap is not None else 0,
        }

    def _run_action(
        self,
        name: str,
        fn: Callable[[], None],
        *,
        source: str = "ui",
    ) -> None:
        self.debug.action(name, source=source, **self._debug_context())
        fn()

    def _sync_connection_buttons(self, *, running: bool | None = None) -> None:
        is_running = self.tap.status.running if running is None else running
        self.btn_connect.setEnabled(not is_running)
        self.btn_disconnect.setEnabled(is_running)
        if is_running:
            self.btn_connect.setObjectName("")
            self.btn_disconnect.setObjectName("Primary")
        else:
            self.btn_connect.setObjectName("Primary")
            self.btn_disconnect.setObjectName("")
        for btn in (self.btn_connect, self.btn_disconnect):
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _chip_color_style(self, color: str) -> str:
        return (
            f"background-color: {COLORS['panel_alt']};"
            f"border: 1px solid {COLORS['border']};"
            f"border-radius: 6px;"
            f"padding: 6px 10px;"
            f"color: {color};"
        )

    def _set_link_state(self, state: str, when: datetime | None = None) -> None:
        stamp = when.strftime("%H:%MZ") if when else None
        if state == "off":
            self.link_chip.setText("LINK off")
            color = COLORS["muted"]
        elif state == "ok":
            self.link_chip.setText(f"LINK ok · {stamp}" if stamp else "LINK ok")
            color = COLORS["ok"]
        elif state == "err":
            self.link_chip.setText(f"LINK err · {stamp}" if stamp else "LINK err")
            color = COLORS["warn"]
        else:
            self.link_chip.setText("LINK …")
            color = COLORS["accent"]
        self.link_chip.setStyleSheet(self._chip_color_style(color))

    def _maybe_auto_connect(self) -> None:
        if self._closing or self.tap.status.running:
            return
        if not self.session.settings.auto_connect():
            return
        if not self._printer_ready():
            self._flash(
                "Auto-connect skipped — pick a printer in Settings first.",
                error=True,
            )
            self.tabs.setCurrentIndex(1)
            return
        self._run_action("start", self._start_tap)

    def _start_tap(self) -> None:
        if not self._printer_ready():
            self._flash("Pick a printer in Settings first.", error=True)
            self.tabs.setCurrentIndex(1)
            return
        try:
            self.tap.start()
        except Exception as exc:  # noqa: BLE001
            self._sync_connection_buttons(running=False)
            self._set_link_state("err")
            self._flash(str(exc), error=True)
            return
        self._sync_connection_buttons(running=True)
        self._set_link_state("ok", datetime.now(UTC))
        self._update_tray_tooltip()
        note = self.tap.status.last_error
        self._flash(note if note else "Connected — watching Hoppie traffic from any aircraft")
        self._reload_messages()

    def _stop_tap(self) -> None:
        self.tap.stop()
        self._sync_connection_buttons(running=False)
        self._set_link_state("off")
        self._update_tray_tooltip()
        self._flash("Disconnected · Hoppie DNS restored.")
        self._reload_messages()

    @Slot(object)
    def _apply_tap_update(self, status: object) -> None:
        if self._closing or not isinstance(status, TapStatus):
            return
        self._sync_connection_buttons(running=status.running)
        stats = status.last_stats or {}
        fields = {
            **self._debug_context(),
            "last_hoppie_type": status.last_hoppie_type or "-",
            "exchanges": status.exchanges,
            "printed": stats.get("printed", 0),
            "stored": stats.get("stored", 0),
            "duplicates": stats.get("duplicates", 0),
        }
        if status.last_error and not status.running:
            self.debug.error("tap", message=status.last_error, **fields)
        else:
            self.debug.info("tap", **fields)
        if not status.running:
            self._set_link_state("off")
        elif status.last_error and "trust setup" not in (status.last_error or ""):
            self._set_link_state("err", status.last_check)
        elif status.last_check:
            self._set_link_state("ok", status.last_check)
        self._update_tray_tooltip()

        new_count = int(stats.get("printed", 0)) + int(stats.get("stored", 0))
        user_check = self._user_check_pending
        if status.last_check is not None or status.last_error:
            self._user_check_pending = False
        if status.last_error and not status.running:
            self._flash(status.last_error, error=True)
        elif new_count > 0:
            printed = int(stats.get("printed", 0))
            if printed:
                self._flash(f"{new_count} new · {printed} printed")
            else:
                self._flash(f"{new_count} new message(s)")
        elif user_check:
            filt = self.session.settings.callsign()
            extra = f" · filter {filt}" if filt else ""
            if status.exchanges:
                self._flash(
                    f"Bridge on · {status.exchanges} msg "
                    f"/ {status.redirects} redirects{extra}"
                )
            elif status.redirects:
                self._flash(
                    f"Bridge on · {status.redirects} redirects, no printable msg yet{extra}"
                )
            else:
                self._flash(
                    f"Bridge on · idle — request ATIS from the plane{extra}"
                )
        # Keep a live counter on the link chip.
        if status.running and status.exchanges:
            self.link_chip.setText(f"LINK {status.exchanges} seen")
        self._reload_messages()

    @Slot(int)
    def _on_new_messages(self, count: int) -> None:
        notify("ACARS Print Bridge", f"{count} new message(s)")

    def _reprint(self) -> None:
        if self._selected_id is None:
            self._flash("Select a message to print.", error=True)
            return
        msg = self.session.messages.get(self._selected_id)
        if not msg:
            return
        settings = self._printer_settings()
        result = self.session.print_manager.print_message(msg, settings, is_reprint=True)
        ok = result == "printed"
        self._flash("Printed." if ok else "Print failed.", error=not ok)

    def _test_print(self) -> None:
        settings = self._printer_settings()
        try:
            self.session.print_manager.test_print(settings)
            self._flash(f"Test print → {settings.destination}")
        except Exception as exc:  # noqa: BLE001
            self._flash(f"Test print failed: {exc}", error=True)

    def _printer_settings(self) -> PrinterSettings:
        return self.session.settings.as_printer_settings()

    def _save_format_settings(self, *, quiet: bool = False) -> None:
        w = self._format_widgets
        self.session.settings.set_aircraft_registration(w["registration"].text().strip())
        printer_label = w["printer"].currentText().strip() or "console (log only)"
        self.session.settings.set_printer_destination(
            destination_from_label(printer_label, self._printer_choices)
        )
        width_value = w["width"].currentData() or "80"
        self.session.settings.set_paper_width(str(width_value))
        self.session.settings.set_cut_enabled(w["cut"].currentText() == "on")
        self.session.settings.set_print_render_mode(
            str(w["print_mode"].currentData() or "bitmap")
        )
        self.session.settings.set_print_font(str(w["print_font"].currentData() or "a"))
        self.session.settings.set_print_glyph_px(w["print_glyph_px"].value())
        self.session.settings.set_print_line_gap_px(w["print_line_gap"].value())
        self.session.settings.set_print_char_width(w["print_char_w"].value())
        self.session.settings.set_print_char_height(w["print_char_h"].value())
        spacing_val = w["print_spacing"].value()
        self.session.settings.set_print_line_spacing_dots(
            None if spacing_val <= 0 else spacing_val
        )
        self.session.settings.set_print_bold(w["print_bold"].currentText() == "on")
        self.session.settings.set_print_columns(w["print_columns"].currentData())
        self.session.settings.set_print_lead_in(w["print_lead_in"].value())
        self.session.settings.set_print_tear_feed(w["print_tear_feed"].value())
        self.session.rebuild_printer()
        if not quiet:
            self._flash("Format saved.")

    def _save_format_and_test(self) -> None:
        self._save_format_settings(quiet=True)
        self._test_print()

    def _reset_format_defaults(self) -> None:
        """Restore Format controls to shipping defaults (printer destination kept)."""
        from acars_bridge.printing.bitmap_render import mm_hint

        w = self._format_widgets
        w["registration"].setText("")
        width_idx = w["width"].findData("80")
        if width_idx >= 0:
            w["width"].setCurrentIndex(width_idx)
        w["cut"].setCurrentText("on")
        mode_idx = w["print_mode"].findData("bitmap")
        if mode_idx >= 0:
            w["print_mode"].setCurrentIndex(mode_idx)
        w["print_glyph_px"].setValue(28)
        w["glyph_hint"].setText(mm_hint(28))
        w["print_line_gap"].setValue(2)
        font_idx = w["print_font"].findData("a")
        if font_idx >= 0:
            w["print_font"].setCurrentIndex(font_idx)
        w["print_char_w"].setValue(1)
        w["print_char_h"].setValue(1)
        w["print_bold"].setCurrentText("off")
        cols_idx = w["print_columns"].findData("auto")
        if cols_idx >= 0:
            w["print_columns"].setCurrentIndex(cols_idx)
        w["print_spacing"].setValue(0)
        w["print_lead_in"].setValue(2)
        w["print_tear_feed"].setValue(6)
        sync = getattr(self, "_sync_format_mode_widgets", None)
        if callable(sync):
            sync()
        self._save_format_settings(quiet=True)
        self._flash("Format reset to defaults (printer unchanged).")

    def _save_settings(self) -> None:
        w = self._settings_widgets
        self.session.settings.set_callsign(w["callsign"].text().strip())
        logon_value = w["logon"].text().strip()
        if logon_value:
            self.session.settings.set_hoppie_logon(logon_value)
            w["logon"].clear()
            w["logon"].setPlaceholderText("stored — leave blank to keep")
        self.session.settings.set_auto_print(w["auto_print"].currentText() == "on")
        self.session.settings.set_auto_connect(w["auto_connect"].currentText() == "on")
        self.session.settings.set_check_updates(
            w["check_updates"].currentText() == "on"
        )
        scale_value = {"85%": 0.85, "100%": 1.0, "115%": 1.15, "125%": 1.25}.get(
            w["ui_scale"].currentText(), 1.0
        )
        prev_scale = self.session.settings.ui_scale()
        self.session.settings.set_ui_scale(scale_value)
        notes: list[str] = []
        self._refresh_header()
        if abs(prev_scale - scale_value) > 0.001:
            app = QApplication.instance()
            if isinstance(app, QApplication):
                apply_theme(app, ui_scale=scale_value)
            notes.append("UI scale applied")
        suffix = f" · {'; '.join(notes)}" if notes else ""
        self._flash(f"Settings saved{suffix}")
        self._reload_messages()
        self._sync_detail_visibility()

    def _tick_clock(self) -> None:
        if self._closing:
            return
        now = datetime.now(UTC).strftime("%H:%MZ")
        self.clock_chip.setText(f"UTC {now}")

    def _show_debug_log(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Debug log")
        dlg.setMinimumSize(760, 520)
        layout = QVBoxLayout(dlg)

        hint = QLabel(
            "Actions, toasts, and tap events are logged here. "
            "Copy and paste into chat, or open the file."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        path_label = QLabel(str(self.debug.path))
        path_label.setObjectName("Muted")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(path_label)

        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setFont(mono_font())
        view.setPlainText(self.debug.paste_block(header=self._debug_header()))
        layout.addWidget(view, stretch=1)

        buttons = QDialogButtonBox()
        copy_btn = buttons.addButton(
            "Copy for chat", QDialogButtonBox.ButtonRole.ActionRole
        )
        open_btn = buttons.addButton(
            "Open folder", QDialogButtonBox.ButtonRole.ActionRole
        )
        clear_btn = buttons.addButton(
            "Clear log", QDialogButtonBox.ButtonRole.ActionRole
        )
        refresh_btn = buttons.addButton(
            "Refresh", QDialogButtonBox.ButtonRole.ActionRole
        )
        close_btn = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        layout.addWidget(buttons)

        def refresh() -> None:
            view.setPlainText(self.debug.paste_block(header=self._debug_header()))
            view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())

        def copy_for_chat() -> None:
            text = self.debug.paste_block(header=self._debug_header())
            QGuiApplication.clipboard().setText(text)
            self.debug.action("copy_debug_log", chars=len(text))
            self._flash("Debug log copied — paste it in chat.")
            refresh()

        def open_folder() -> None:
            folder = str(self.debug.path.parent)
            self.debug.action("open_debug_folder", path=folder)
            try:
                if sys.platform.startswith("linux"):
                    subprocess.Popen(  # noqa: S603
                        ["xdg-open", folder],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                elif sys.platform == "darwin":
                    subprocess.Popen(  # noqa: S603
                        ["open", folder],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                elif os.name == "nt":
                    os.startfile(folder)  # type: ignore[attr-defined]
                else:
                    self._flash(f"Log folder: {folder}")
            except OSError as exc:
                self._flash(f"Could not open folder: {exc}", error=True)

        def clear_log() -> None:
            self.debug.clear()
            refresh()
            self._flash("Debug log cleared.")

        copy_btn.clicked.connect(copy_for_chat)
        open_btn.clicked.connect(open_folder)
        clear_btn.clicked.connect(clear_log)
        refresh_btn.clicked.connect(refresh)
        close_btn.clicked.connect(dlg.accept)
        refresh()
        dlg.exec()

    def _debug_header(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "data_dir": str(self.session.paths.root),
            "log_file": str(self.debug.path),
            **self._debug_context(),
            "tap_exchanges": self.tap.status.exchanges,
            "tap_last_type": self.tap.status.last_hoppie_type or "-",
            "tap_last_error": self.tap.status.last_error or "-",
        }

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        # Always exit on X / Quit. Do not hide to tray — elevated Windows
        # builds often lose the tray icon and leave a ghost process holding app.lock.
        if self._closing:
            event.accept()
            super().closeEvent(event)
            return
        self._closing = True
        self._quit_requested = True
        try:
            self.debug.info("app_closing", **self._debug_context())
        except Exception:  # noqa: BLE001
            pass
        try:
            self._clock_timer.stop()
        except Exception:  # noqa: BLE001
            pass
        if self._tray is not None:
            try:
                self._tray.hide()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.tap.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.session.close()
        except Exception:  # noqa: BLE001
            pass
        event.accept()
        super().closeEvent(event)
        app = QApplication.instance()
        if app is not None:
            app.quit()
        # WinDivert / proxy threads can keep the process alive after Qt exits.
        QTimer.singleShot(2000, lambda: os._exit(0))

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt API
        # Minimize stays on the taskbar (normal). No hide-to-tray.
        super().changeEvent(event)


def _lock_holder_pid(lock: object) -> int | None:
    try:
        info = lock.getLockInfo()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return None
    if not info:
        return None
    try:
        pid = int(info[0])
    except (TypeError, ValueError, IndexError):
        return None
    return pid if pid > 0 else None


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        out = (completed.stdout or "").strip()
        return str(pid) in out and "No tasks" not in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _force_quit_pid(pid: int) -> tuple[bool, str]:
    """Kill a stuck previous instance (works when this process is elevated)."""
    if pid <= 0:
        return False, "Invalid process id."
    if pid == os.getpid():
        return False, "Refusing to kill the current process."
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)
        detail = (completed.stderr or completed.stdout or "").strip()
        if completed.returncode == 0 or not _process_alive(pid):
            return True, detail or f"Ended PID {pid}."
        return False, detail or f"taskkill failed for PID {pid}."
    try:
        os.kill(pid, 9)
    except OSError as exc:
        return False, str(exc)
    return True, f"Ended PID {pid}."


def _acquire_single_instance_lock(lock: object) -> bool:
    """Take app.lock, offering to force-quit a live previous instance."""
    lock.setStaleLockTime(5_000)  # type: ignore[attr-defined]
    lock.removeStaleLockFile()  # type: ignore[attr-defined]
    if lock.tryLock(100):  # type: ignore[attr-defined]
        return True

    pid = _lock_holder_pid(lock)
    alive = _process_alive(pid) if pid else False
    app = QApplication.instance() or QApplication(sys.argv)

    if alive and pid is not None:
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("ACARS Print Bridge")
        box.setText("ACARS Print Bridge is already running.")
        box.setInformativeText(
            f"A previous instance (PID {pid}) is still alive — often with no "
            "tray icon when running as Administrator.\n\n"
            "Force quit it and start this copy?"
        )
        force = box.addButton("Force quit previous", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not force:
            return False
        ok, detail = _force_quit_pid(pid)
        if not ok:
            QMessageBox.critical(
                None,
                "ACARS Print Bridge",
                f"Could not end the previous instance.\n\n{detail}\n\n"
                "Open Task Manager as Administrator and end "
                '"ACARS Print Bridge.exe", then try again.',
            )
            return False
        # Give Windows a moment to release the lock file handle.
        time.sleep(0.4)
        lock.removeStaleLockFile()  # type: ignore[attr-defined]
        if lock.tryLock(500):  # type: ignore[attr-defined]
            return True
        QMessageBox.critical(
            None,
            "ACARS Print Bridge",
            "Previous instance was ended, but the lock file is still held.\n"
            "Wait a second and open the app again.",
        )
        return False

    # Stale lock / dead PID — clear and retry.
    lock.removeStaleLockFile()  # type: ignore[attr-defined]
    if lock.tryLock(500):  # type: ignore[attr-defined]
        return True
    QMessageBox.warning(
        None,
        "ACARS Print Bridge",
        "ACARS Print Bridge could not start (lock busy).\n"
        "End any leftover process in Task Manager, then try again.",
    )
    _ = app  # keep QApplication alive for the dialog
    return False


def run_app(paths: AppPaths | None = None) -> None:
    from PySide6.QtCore import QLockFile

    resolved = paths or AppPaths.default()
    lock = QLockFile(str(resolved.root / "app.lock"))
    if not _acquire_single_instance_lock(lock):
        return

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    assert isinstance(app, QApplication)

    session = build_session(resolved)
    apply_theme(app, ui_scale=session.settings.ui_scale())
    app.setWindowIcon(make_app_icon())
    window = AcarsBridgeApp(session)
    window.show()
    try:
        app.exec()
    finally:
        try:
            lock.unlock()
        except Exception:  # noqa: BLE001
            pass
        # Absolute last resort if anything non-daemon is still wedged.
        os._exit(0)
