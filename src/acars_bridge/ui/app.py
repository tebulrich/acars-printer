from __future__ import annotations

import os
import subprocess
import sys
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
    QPlainTextEdit,
    QPushButton,
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
        self._tray_hint_shown = False
        self._printer_choices = list_printer_choices(session.settings.printer_destination())
        self._settings_widgets: dict[str, Any] = {}

        self.setWindowTitle(f"ACARS Print Bridge  ·  {__version__}")
        self.setMinimumSize(960, 640)
        self.resize(1100, 720)
        self._app_icon = make_app_icon()
        self.setWindowIcon(self._app_icon)

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
        for btn in (self.btn_connect, self.btn_disconnect, self.btn_debug):
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
        self.tab_settings = QWidget()
        self.tabs.addTab(self.tab_messages, "Messages")
        self.tabs.addTab(self.tab_settings, "Settings")
        self._build_messages_tab()
        self._build_settings_tab()
        row.addWidget(self.tabs, stretch=2)
        row.addWidget(self._build_detail(), stretch=3)
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
            "Connect as Administrator, then keep flying — any Hoppie aircraft. "
            "This app watches Hoppie traffic on your PC and prints it. "
            "Leave the callsign filter empty unless you only want one flight."
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
        layout.setContentsMargins(18, 18, 18, 18)

        self.detail_title = QLabel("Select a message")
        self.detail_title.setObjectName("Title")
        self.detail_meta = QLabel("New traffic from your aircraft client appears here and prints.")
        self.detail_meta.setObjectName("Muted")
        self.detail_meta.setWordWrap(True)
        layout.addWidget(self.detail_title)
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
        self.btn_test_print = QPushButton("Test print")
        self.btn_test_print.clicked.connect(
            lambda: self._run_action("test_print", self._test_print)
        )
        action_row.addWidget(self.btn_print)
        action_row.addWidget(self.btn_test_print)
        action_row.addStretch(1)
        layout.addLayout(action_row)
        return detail

    def _build_settings_tab(self) -> None:
        form = QFormLayout(self.tab_settings)
        form.setContentsMargins(16, 16, 16, 16)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

        callsign = QLineEdit(self.session.settings.callsign() or "")
        callsign.setPlaceholderText("optional — only print this flight")

        registration = QLineEdit(self.session.settings.aircraft_registration() or "")
        registration.setPlaceholderText("optional tail — omit REG if empty")

        logon = QLineEdit()
        logon.setEchoMode(QLineEdit.EchoMode.Password)
        logon.setPlaceholderText(
            "stored — leave blank to keep"
            if self.session.settings.hoppie_logon()
            else "Hoppie ACARS logon code (not your Windows user)"
        )

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
            "registration": registration,
            "logon": logon,
            "printer": printer,
            "width": width,
            "cut": cut,
            "auto_print": auto_print,
            "auto_connect": auto_connect,
            "check_updates": check_updates,
            "ui_scale": ui_scale,
        }

        form.addRow("Callsign filter", callsign)
        form.addRow("Aircraft registration", registration)
        form.addRow("Hoppie logon", logon)
        form.addRow("Printer", printer)
        form.addRow("Paper width", width)
        form.addRow("Cut / tear assist", cut)
        form.addRow("Auto-print", auto_print)
        form.addRow("Auto-connect", auto_connect)
        form.addRow("Check for updates", check_updates)
        form.addRow("UI scale", ui_scale)

        help_lbl = QLabel(
            "Hoppie logon is the secret ACARS code from hoppie.nl (not a Windows "
            "username). The bridge injects it when the plane sends a blank/wrong "
            "logon. Connect as Administrator to intercept; Disconnect restores "
            "normal Hoppie access. Auto-connect starts the tap when the app "
            "opens (still needs Administrator). Updates check GitHub Releases "
            "and can one-click install the Windows exe. Cut / tear assist feeds "
            "paper to the tear bar."
        )
        help_lbl.setObjectName("Muted")
        help_lbl.setWordWrap(True)
        form.addRow(help_lbl)

        save = QPushButton("Save settings")
        save.setObjectName("Primary")
        save.clicked.connect(
            lambda: self._run_action("save_settings", self._save_settings)
        )
        check_btn = QPushButton("Check for updates now")
        check_btn.clicked.connect(lambda: self._updates.check(manual=True))
        form.addRow(save)
        form.addRow(check_btn)

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.debug.info("tray", available=False)
            return
        tray = QSystemTrayIcon(self._app_icon, self)
        tray.setToolTip("ACARS Print Bridge")
        menu = QMenu(self)
        show_action = QAction("Show window", self)
        show_action.triggered.connect(self._show_from_tray)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit_from_tray)
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
        self._quit_requested = True
        self.close()

    @Slot(QSystemTrayIcon.ActivationReason)
    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
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
            return
        for msg in rows:
            self.message_list.addItem(self._message_item(msg))
        self.message_list.blockSignals(False)
        if self._selected_id is None and rows:
            self._select_message(rows[0].id)
        elif self._selected_id in self._message_ids:
            self._select_message(self._selected_id)

    def _message_item(self, msg: StoredMessage) -> QListWidgetItem:
        preview = msg.normalized_body.replace("\n", " · ")[:64]
        direction = "OUT" if msg.direction == "out" else "IN"
        label = (
            f"{direction}  {msg.sender or msg.to_station or '?'}  "
            f"{msg.message_type.upper()}\n{preview}"
        )
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, msg.id)
        return item

    def _on_list_selection(self) -> None:
        items = self.message_list.selectedItems()
        if not items:
            return
        mid = items[0].data(Qt.ItemDataRole.UserRole)
        if isinstance(mid, int):
            self._select_message(mid)

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
        return PrinterSettings(
            destination=self.session.settings.printer_destination(),
            paper_width=self.session.settings.paper_width(),
            cut_enabled=self.session.settings.cut_enabled(),
            aircraft_registration=self.session.settings.aircraft_registration(),
        )

    def _save_settings(self) -> None:
        w = self._settings_widgets
        self.session.settings.set_callsign(w["callsign"].text().strip())
        self.session.settings.set_aircraft_registration(w["registration"].text().strip())
        logon_value = w["logon"].text().strip()
        if logon_value:
            self.session.settings.set_hoppie_logon(logon_value)
            w["logon"].clear()
            w["logon"].setPlaceholderText("stored — leave blank to keep")
        printer_label = w["printer"].currentText().strip() or "console (log only)"
        self.session.settings.set_printer_destination(
            destination_from_label(printer_label, self._printer_choices)
        )
        width_value = w["width"].currentData() or "80"
        self.session.settings.set_paper_width(str(width_value))
        self.session.settings.set_cut_enabled(w["cut"].currentText() == "on")
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
        self.session.rebuild_printer()
        self._refresh_header()
        if abs(prev_scale - scale_value) > 0.001:
            app = QApplication.instance()
            if isinstance(app, QApplication):
                apply_theme(app, ui_scale=scale_value)
            notes.append("UI scale applied")
        suffix = f" · {'; '.join(notes)}" if notes else ""
        self._flash(f"Settings saved{suffix} — Connect as Administrator when ready.")
        self._reload_messages()

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
        # Close / X → tray (keep watching Hoppie). Quit from the tray menu exits.
        if (
            not self._quit_requested
            and self._tray is not None
            and self._tray.isVisible()
        ):
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self._tray.showMessage(
                    "ACARS Print Bridge",
                    "Still running in the tray. Right-click the icon → Quit to exit.",
                    QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )
            return
        self._closing = True
        self.debug.info("app_closing", **self._debug_context())
        self._clock_timer.stop()
        if self._tray is not None:
            self._tray.hide()
        self.tap.stop()
        self.session.close()
        super().closeEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt API
        # Minimize also parks in the tray when available.
        from PySide6.QtCore import QEvent

        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self._tray is not None
            and self._tray.isVisible()
            and not self._quit_requested
        ):
            event.accept()
            QTimer.singleShot(0, self.hide)
            return
        super().changeEvent(event)


def run_app(paths: AppPaths | None = None) -> None:
    import sys

    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QMessageBox

    resolved = paths or AppPaths.default()
    lock = QLockFile(str(resolved.root / "app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        # Second launch (common with UAC) — keep the first instance only.
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.warning(
            None,
            "ACARS Print Bridge",
            "ACARS Print Bridge is already running.\n"
            "Close the other window (or end it in Task Manager) and try again.",
        )
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
        lock.unlock()
