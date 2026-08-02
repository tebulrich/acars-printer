from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QTextOption
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from acars_bridge import __version__
from acars_bridge.config import AppPaths
from acars_bridge.hoppie.errors import HoppieError, SendNotAllowedError
from acars_bridge.hoppie.requests import AtisSide, AtisSource, WeatherKind
from acars_bridge.hoppie.types import ClientMode, MessageType
from acars_bridge.models.messages import StoredMessage
from acars_bridge.printing.base import PrinterSettings
from acars_bridge.printing.discovery import (
    destination_from_label,
    label_for_destination,
    list_printer_choices,
)
from acars_bridge.redaction import mask_logon
from acars_bridge.services.debug_log import DebugLog
from acars_bridge.services.poller import BackgroundPoller, PollerStatus
from acars_bridge.services.session import AppSession, build_session
from acars_bridge.ui.global_hotkeys import GlobalHotkeyManager
from acars_bridge.ui.hotkeys import (
    HOTKEY_ACTIONS,
    HotkeyBindingError,
    help_text,
    normalize_sequence,
    save_binding,
    sequence_is_safe_global,
)
from acars_bridge.ui.notifications import notify
from acars_bridge.ui.theme import COLORS, apply_theme, mono_font


class _PollerBridge(QObject):
    """Marshal background poller callbacks onto the Qt UI thread."""

    updated = Signal(object)
    new_messages = Signal(int)


class AcarsBridgeApp(QMainWindow):
    def __init__(self, session: AppSession) -> None:
        super().__init__()
        self.session = session
        self._selected_id: int | None = None
        self._message_ids: list[int] = []
        self._closing = False
        self._printer_choices = list_printer_choices(session.settings.printer_destination())
        self._settings_widgets: dict[str, Any] = {}
        self._request_widgets: dict[str, Any] = {}
        self._hotkey_editors: dict[str, QKeySequenceEdit] = {}
        self._actions: dict[str, Callable[[], None]] = {}

        self.setWindowTitle(f"ACARS Print Bridge  ·  {__version__}")
        self.setFixedSize(1180, 760)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)

        self._bridge = _PollerBridge(self)
        self._bridge.updated.connect(self._apply_poller_update)
        self._bridge.new_messages.connect(self._on_new_messages)

        self.poller = BackgroundPoller(
            session,
            on_update=lambda status: self._bridge.updated.emit(status),
            on_new_messages=lambda count: self._bridge.new_messages.emit(count),
        )

        self._hotkeys = GlobalHotkeyManager(self)
        self._hotkeys.activated.connect(self._on_hotkey_action)
        self._hotkeys.status_changed.connect(self._on_hotkey_status)

        self.debug = DebugLog(session.paths.root / "debug.log")
        self.debug.info(
            "app_ready",
            version=__version__,
            **self._debug_context(),
        )

        self._build_ui()
        self._register_actions()
        self._apply_hotkey_bindings()
        self._refresh_header()
        self._reload_messages()

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self._tick_clock()

    # ----- layout -----

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_body(), stretch=1)
        layout.addWidget(self._build_compose())

        self.toast = QLabel("")
        self.toast.setObjectName("Toast")
        self.toast.setProperty("error", False)
        self.toast.setContentsMargins(14, 8, 14, 10)
        layout.addWidget(self.toast)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        row = QHBoxLayout(header)
        row.setContentsMargins(18, 14, 16, 14)

        brand_col = QVBoxLayout()
        brand = QLabel("ACARS PRINT BRIDGE")
        brand.setObjectName("Brand")
        self.subtitle = QLabel("Hoppie station · thermal copy")
        self.subtitle.setObjectName("Subtitle")
        brand_col.addWidget(brand)
        brand_col.addWidget(self.subtitle)
        row.addLayout(brand_col)
        row.addStretch(1)

        self.mode_chip = self._chip("MODE —")
        self.callsign_chip = self._chip("FLT —")
        self.link_chip = self._chip("LINK idle")
        self.clock_chip = self._chip("UTC —")
        for chip in (
            self.mode_chip,
            self.callsign_chip,
            self.link_chip,
            self.clock_chip,
        ):
            row.addWidget(chip)

        self.btn_start = QPushButton("Start")
        self.btn_start.setObjectName("Primary")
        self.btn_start.clicked.connect(lambda: self._run_action("start", self._start_poller))
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.clicked.connect(lambda: self._run_action("pause", self._stop_poller))
        self.btn_check = QPushButton("Check")
        self.btn_check.clicked.connect(lambda: self._run_action("check_now", self._check_now))
        self.btn_help = QPushButton("Shortcuts")
        self.btn_help.clicked.connect(
            lambda: self._run_action("help", self._show_hotkey_help)
        )
        self.btn_debug = QPushButton("Debug")
        self.btn_debug.clicked.connect(self._show_debug_log)
        for btn in (
            self.btn_start,
            self.btn_pause,
            self.btn_check,
            self.btn_help,
            self.btn_debug,
        ):
            row.addWidget(btn)
        return header

    def _build_body(self) -> QWidget:
        body = QWidget()
        row = QHBoxLayout(body)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(10)

        self.tabs = QTabWidget()
        self.tab_messages = QWidget()
        self.tab_requests = QWidget()
        self.tab_settings = QWidget()
        self.tab_shortcuts = QWidget()
        self.tabs.addTab(self.tab_messages, "Messages")
        self.tabs.addTab(self.tab_requests, "Requests")
        self.tabs.addTab(self.tab_settings, "Settings")
        self.tabs.addTab(self.tab_shortcuts, "Shortcuts")
        self._build_messages_tab()
        self._build_requests_tab()
        self._build_settings_tab()
        self._build_shortcuts_tab()
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
        self.btn_refresh.clicked.connect(
            lambda: self._run_action("reload", self._reload_messages)
        )
        head.addWidget(self.btn_refresh)
        layout.addLayout(head)

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
        self.detail_meta = QLabel(
            "Assign global shortcuts under Shortcuts. Replies: WILCO / ROGER / UNABLE / STANDBY."
        )
        self.detail_meta.setObjectName("Muted")
        self.detail_meta.setWordWrap(True)
        layout.addWidget(self.detail_title)
        layout.addWidget(self.detail_meta)

        self.detail_body = QPlainTextEdit()
        self.detail_body.setReadOnly(True)
        self.detail_body.setFont(mono_font())
        self.detail_body.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        layout.addWidget(self.detail_body, stretch=1)

        reply_row = QHBoxLayout()
        for label, reply in (
            ("WILCO", "WILCO"),
            ("ROGER", "ROGER"),
            ("UNABLE", "UNABLE"),
            ("STANDBY", "STANDBY"),
        ):
            btn = QPushButton(label)
            btn.setObjectName("Primary")
            btn.clicked.connect(
                lambda _=False, r=reply: self._run_action(
                    f"reply_{r.lower()}", lambda: self._reply(r)
                )
            )
            reply_row.addWidget(btn)
        reply_row.addStretch(1)
        layout.addLayout(reply_row)

        action_row = QHBoxLayout()
        self.btn_print = QPushButton("Print")
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

    def _build_compose(self) -> QWidget:
        compose = QFrame()
        compose.setObjectName("Compose")
        row = QHBoxLayout(compose)
        row.setContentsMargins(18, 14, 18, 14)
        label = QLabel("Telex")
        label.setObjectName("Muted")
        row.addWidget(label)
        self.telex_to = QLineEdit()
        self.telex_to.setPlaceholderText("TO")
        self.telex_to.setFixedWidth(210)
        row.addWidget(self.telex_to)
        self.telex_body = QLineEdit()
        self.telex_body.setPlaceholderText("Message")
        self.telex_body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(self.telex_body, stretch=1)
        self.btn_send = QPushButton("Send")
        self.btn_send.setObjectName("Primary")
        self.btn_send.clicked.connect(
            lambda: self._run_action("send_telex", self._send_telex)
        )
        row.addWidget(self.btn_send)
        return compose

    def _build_requests_tab(self) -> None:
        outer = QVBoxLayout(self.tab_requests)
        outer.setContentsMargins(8, 8, 8, 8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(10)

        note = QLabel(
            "Station mode only (owns callsign). METAR/TAF/ATIS reply inline; "
            "PDC replies arrive on the next poll. Position is manual — no sim GPS."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        # --- Weather / ATIS ---
        wx_title = QLabel("Weather / ATIS")
        wx_title.setObjectName("Title")
        layout.addWidget(wx_title)
        wx_form = QFormLayout()
        wx_form.setHorizontalSpacing(12)
        wx_form.setVerticalSpacing(8)
        last_icao = self.session.settings.get("req_last_icao", "") or ""
        icao = QLineEdit(last_icao)
        icao.setPlaceholderText("EGLL")
        icao.setMaxLength(4)
        atis_side = QComboBox()
        atis_side.addItem("Departure", AtisSide.DEP.value)
        atis_side.addItem("Arrival", AtisSide.ARR.value)
        saved_side = self.session.settings.get("req_atis_side", AtisSide.DEP.value)
        idx = atis_side.findData(saved_side)
        if idx >= 0:
            atis_side.setCurrentIndex(idx)
        atis_source = QComboBox()
        for label, value in (
            ("VATSIM", AtisSource.VATSIM.value),
            ("IVAO", AtisSource.IVAO.value),
            ("PilotEdge", AtisSource.PILOTEDGE.value),
        ):
            atis_source.addItem(label, value)
        saved_src = self.session.settings.get("req_atis_source", AtisSource.VATSIM.value)
        src_idx = atis_source.findData(saved_src)
        if src_idx >= 0:
            atis_source.setCurrentIndex(src_idx)
        wx_form.addRow("Airport ICAO", icao)
        wx_form.addRow("ATIS side", atis_side)
        wx_form.addRow("ATIS source", atis_source)
        layout.addLayout(wx_form)
        wx_btns = QHBoxLayout()
        btn_metar = QPushButton("METAR")
        btn_metar.setObjectName("Primary")
        btn_taf = QPushButton("TAF")
        btn_atis = QPushButton("ATIS")
        btn_metar.clicked.connect(
            lambda: self._run_action("request_metar", self._request_metar)
        )
        btn_taf.clicked.connect(lambda: self._run_action("request_taf", self._request_taf))
        btn_atis.clicked.connect(
            lambda: self._run_action("request_atis", self._request_atis)
        )
        for btn in (btn_metar, btn_taf, btn_atis):
            wx_btns.addWidget(btn)
        wx_btns.addStretch(1)
        layout.addLayout(wx_btns)

        # --- PDC ---
        pdc_title = QLabel("Pre-departure clearance")
        pdc_title.setObjectName("Title")
        layout.addWidget(pdc_title)
        pdc_form = QFormLayout()
        pdc_form.setHorizontalSpacing(12)
        pdc_form.setVerticalSpacing(8)
        s = self.session.settings
        pdc_station = QLineEdit(s.get("req_pdc_station", "") or "")
        pdc_station.setPlaceholderText("EGLL or EGLL_DEL")
        pdc_dep = QLineEdit(s.get("req_pdc_dep", "") or "")
        pdc_dep.setPlaceholderText("EGLL")
        pdc_dep.setMaxLength(4)
        pdc_dest = QLineEdit(s.get("req_pdc_dest", "") or "")
        pdc_dest.setPlaceholderText("EDDM")
        pdc_dest.setMaxLength(4)
        pdc_type = QLineEdit(s.get("req_pdc_actype", "A320") or "A320")
        pdc_stand = QLineEdit(s.get("req_pdc_stand", "") or "")
        pdc_stand.setPlaceholderText("A36")
        pdc_atis = QLineEdit(s.get("req_pdc_atis", "") or "")
        pdc_atis.setPlaceholderText("D")
        pdc_atis.setMaxLength(1)
        pdc_form.addRow("Station (TO)", pdc_station)
        pdc_form.addRow("Departure", pdc_dep)
        pdc_form.addRow("Destination", pdc_dest)
        pdc_form.addRow("A/C type", pdc_type)
        pdc_form.addRow("Stand / gate", pdc_stand)
        pdc_form.addRow("ATIS letter", pdc_atis)
        layout.addLayout(pdc_form)
        btn_pdc = QPushButton("Send PDC")
        btn_pdc.setObjectName("Primary")
        btn_pdc.clicked.connect(lambda: self._run_action("request_pdc", self._request_pdc))
        layout.addWidget(btn_pdc, alignment=Qt.AlignmentFlag.AlignLeft)

        # --- Position ---
        pos_title = QLabel("Position report")
        pos_title.setObjectName("Title")
        layout.addWidget(pos_title)
        pos_hint = QLabel("Manual entry — Fenix auto-fills this from the FMS.")
        pos_hint.setObjectName("Muted")
        pos_hint.setWordWrap(True)
        layout.addWidget(pos_hint)
        pos_form = QFormLayout()
        pos_form.setHorizontalSpacing(12)
        pos_form.setVerticalSpacing(8)
        pos_to = QLineEdit(s.get("req_pos_to", "") or "")
        pos_to.setPlaceholderText("ATC / OPS")
        pos_lat = QLineEdit()
        pos_lat.setPlaceholderText("N5030.0")
        pos_lon = QLineEdit()
        pos_lon.setPlaceholderText("E00845.0")
        pos_alt = QLineEdit()
        pos_alt.setPlaceholderText("FL360")
        pos_time = QLineEdit(datetime.now(UTC).strftime("%H%MZ"))
        pos_next = QLineEdit()
        pos_next.setPlaceholderText("Optional")
        pos_eta = QLineEdit()
        pos_eta.setPlaceholderText("Optional HHMMZ")
        pos_form.addRow("TO", pos_to)
        pos_form.addRow("Latitude", pos_lat)
        pos_form.addRow("Longitude", pos_lon)
        pos_form.addRow("Altitude", pos_alt)
        pos_form.addRow("Time UTC", pos_time)
        pos_form.addRow("Next", pos_next)
        pos_form.addRow("ETA", pos_eta)
        layout.addLayout(pos_form)
        btn_pos = QPushButton("Send position")
        btn_pos.setObjectName("Primary")
        btn_pos.clicked.connect(
            lambda: self._run_action("send_position", self._send_position_report)
        )
        layout.addWidget(btn_pos, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addStretch(1)
        self._request_widgets = {
            "icao": icao,
            "atis_side": atis_side,
            "atis_source": atis_source,
            "pdc_station": pdc_station,
            "pdc_dep": pdc_dep,
            "pdc_dest": pdc_dest,
            "pdc_type": pdc_type,
            "pdc_stand": pdc_stand,
            "pdc_atis": pdc_atis,
            "pos_to": pos_to,
            "pos_lat": pos_lat,
            "pos_lon": pos_lon,
            "pos_alt": pos_alt,
            "pos_time": pos_time,
            "pos_next": pos_next,
            "pos_eta": pos_eta,
        }
        scroll.setWidget(host)
        outer.addWidget(scroll)

    def _build_settings_tab(self) -> None:
        form = QFormLayout(self.tab_settings)
        form.setContentsMargins(16, 16, 16, 16)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

        callsign = QLineEdit(self.session.settings.callsign() or "")
        logon = QLineEdit()
        logon.setEchoMode(QLineEdit.EchoMode.Password)
        logon.setPlaceholderText(
            mask_logon(self.session.settings.hoppie_logon()) or "enter logon"
        )

        mode = QComboBox()
        mode.addItems(["station", "observer"])
        mode.setCurrentText(self.session.settings.mode().value)

        printer = QComboBox()
        labels = [c.label for c in self._printer_choices]
        printer.addItems(labels)
        current = label_for_destination(self.session.settings.printer_destination())
        if current in labels:
            printer.setCurrentText(current)

        width = QComboBox()
        width.addItems(["58", "80"])
        width.setCurrentText(self.session.settings.paper_width())

        auto_print = QComboBox()
        auto_print.addItems(["on", "off"])
        auto_print.setCurrentText("on" if self.session.settings.auto_print() else "off")

        interval = QLineEdit(str(self.session.settings.poll_interval()))

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
            "mode": mode,
            "printer": printer,
            "width": width,
            "auto_print": auto_print,
            "interval": interval,
            "ui_scale": ui_scale,
        }

        form.addRow("Callsign", callsign)
        form.addRow("Hoppie logon", logon)
        form.addRow("Mode", mode)
        form.addRow("Printer", printer)
        form.addRow("Paper width", width)
        form.addRow("Auto-print", auto_print)
        form.addRow("Poll interval (sec)", interval)
        form.addRow("UI scale", ui_scale)

        help_lbl = QLabel(
            "Station owns the Hoppie callsign (poll + send). "
            "Observer peeks beside PMDG/TFDi (same Hoppie logon) — no send. "
            "Printer: pick «driver» for laser/inkjet (Brother), "
            "«POS ESC/POS» for thermal receipt printers on the same CUPS queue, "
            "or a tcp://… entry for a network POS. "
            "Shortcuts are on the Shortcuts tab (unset by default)."
        )
        help_lbl.setObjectName("Muted")
        help_lbl.setWordWrap(True)
        form.addRow(help_lbl)

        save = QPushButton("Save settings")
        save.setObjectName("Primary")
        save.clicked.connect(
            lambda: self._run_action("save_settings", self._save_settings)
        )
        form.addRow(save)

    def _build_shortcuts_tab(self) -> None:
        outer = QVBoxLayout(self.tab_shortcuts)
        outer.setContentsMargins(12, 12, 12, 12)

        intro = QLabel(
            "All shortcuts start unset. Click a field and press a key combo. "
            "Shortcuts are global (work while another window is focused). "
            "Use Ctrl/Alt/Meta or an F-key — bare letters are blocked so they "
            "don't steal typing from other apps."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        self.hotkey_status = QLabel("")
        self.hotkey_status.setObjectName("Muted")
        self.hotkey_status.setWordWrap(True)
        outer.addWidget(self.hotkey_status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        bindings = self.session.settings.hotkey_bindings()
        self._hotkey_editors.clear()
        for row, item in enumerate(HOTKEY_ACTIONS):
            label = QLabel(item.label)
            editor = QKeySequenceEdit()
            seq = bindings.get(item.action, "")
            if seq:
                editor.setKeySequence(QKeySequence(seq))
            clear = QPushButton("Clear")
            clear.setFixedWidth(72)
            clear.clicked.connect(editor.clear)
            grid.addWidget(label, row, 0)
            grid.addWidget(editor, row, 1)
            grid.addWidget(clear, row, 2)
            self._hotkey_editors[item.action] = editor

        scroll.setWidget(host)
        outer.addWidget(scroll, stretch=1)

        btn_row = QHBoxLayout()
        save = QPushButton("Save shortcuts")
        save.setObjectName("Primary")
        save.clicked.connect(
            lambda: self._run_action("save_shortcuts", self._save_shortcuts)
        )
        clear_all = QPushButton("Clear all")
        clear_all.clicked.connect(
            lambda: self._run_action("clear_shortcuts", self._clear_all_shortcuts)
        )
        btn_row.addWidget(save)
        btn_row.addWidget(clear_all)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

    def _chip(self, text: str) -> QLabel:
        chip = QLabel(text)
        chip.setObjectName("Chip")
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return chip

    # ----- hotkeys -----

    def _register_actions(self) -> None:
        self._actions = {
            "check_now": self._check_now,
            "start": self._start_poller,
            "pause": self._stop_poller,
            "reload": self._reload_messages,
            "tab_messages": lambda: self.tabs.setCurrentIndex(0),
            "tab_settings": lambda: self.tabs.setCurrentIndex(2),
            "save_settings": self._save_settings,
            "reprint": self._reprint,
            "test_print": self._test_print,
            "send_telex": self._send_telex,
            "focus_telex": self.telex_body.setFocus,
            "focus_telex_to": self.telex_to.setFocus,
            "select_prev": lambda: self._select_relative(-1),
            "select_next": lambda: self._select_relative(1),
            "help": self._show_hotkey_help,
            "reply_wilco": lambda: self._reply("WILCO"),
            "reply_roger": lambda: self._reply("ROGER"),
            "reply_unable": lambda: self._reply("UNABLE"),
            "reply_standby": lambda: self._reply("STANDBY"),
        }

    def _apply_hotkey_bindings(self) -> None:
        bindings = self.session.settings.hotkey_bindings()
        try:
            self._hotkeys.set_bindings(bindings)
        except HotkeyBindingError as exc:
            self._flash(str(exc), error=True)
            self._hotkeys.set_bindings({})
        self._refresh_button_shortcut_hints(bindings)

    def _refresh_button_shortcut_hints(self, bindings: dict[str, str]) -> None:
        def label(base: str, action: str) -> str:
            seq = bindings.get(action, "")
            return f"{base}  {seq}" if seq else base

        self.btn_start.setText(label("Start", "start"))
        self.btn_pause.setText(label("Pause", "pause"))
        self.btn_check.setText(label("Check", "check_now"))
        self.btn_help.setText(label("Shortcuts", "help"))
        self.btn_refresh.setText(label("Refresh", "reload"))
        self.btn_print.setText(label("Print", "reprint"))
        self.btn_test_print.setText(label("Test print", "test_print"))
        self.btn_send.setText(label("Send", "send_telex"))

    @Slot(str)
    def _on_hotkey_action(self, action: str) -> None:
        if self._closing:
            return
        # Bring window forward for focus-oriented actions.
        if action in {"focus_telex", "focus_telex_to", "tab_messages", "tab_settings", "help"}:
            self.raise_()
            self.activateWindow()
        fn = self._actions.get(action)
        if fn is not None:
            self._run_action(action, fn, source="hotkey")

    @Slot(str)
    def _on_hotkey_status(self, message: str) -> None:
        if message:
            self.debug.info("hotkey_status", message=message)
        if hasattr(self, "hotkey_status"):
            self.hotkey_status.setText(message)

    def _collect_shortcut_editors(self) -> dict[str, str]:
        bindings: dict[str, str] = {}
        for action, editor in self._hotkey_editors.items():
            seq = normalize_sequence(editor.keySequence())
            if seq:
                bindings[action] = seq
        return bindings

    def _save_shortcuts(self) -> None:
        bindings = self._collect_shortcut_editors()
        for action, seq in bindings.items():
            if not sequence_is_safe_global(seq):
                self._flash(
                    f"{seq} is not allowed globally — use Ctrl/Alt/Meta or an F-key.",
                    error=True,
                )
                return
        try:
            # validate via manager
            from acars_bridge.ui.hotkeys import validate_bindings

            validate_bindings(bindings)
        except HotkeyBindingError as exc:
            self._flash(str(exc), error=True)
            return

        for item in HOTKEY_ACTIONS:
            save_binding(self.session.settings, item.action, bindings.get(item.action, ""))
        self._apply_hotkey_bindings()
        self._flash("Shortcuts saved.")

    def _clear_all_shortcuts(self) -> None:
        for editor in self._hotkey_editors.values():
            editor.clear()
        for item in HOTKEY_ACTIONS:
            save_binding(self.session.settings, item.action, None)
        self._apply_hotkey_bindings()
        self._flash("All shortcuts cleared.")

    def _select_relative(self, delta: int) -> None:
        if not self._message_ids:
            return
        if self._selected_id in self._message_ids:
            idx = self._message_ids.index(self._selected_id)
        else:
            idx = 0
        idx = max(0, min(len(self._message_ids) - 1, idx + delta))
        self._select_message(self._message_ids[idx])

    def _show_hotkey_help(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Keyboard shortcuts")
        dlg.resize(720, 640)
        layout = QVBoxLayout(dlg)
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setFont(mono_font(12))
        box.setPlainText(help_text(self.session.settings.hotkey_bindings()))
        layout.addWidget(box)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        buttons.clicked.connect(dlg.accept)
        layout.addWidget(buttons)
        close = QAction(dlg)
        close.setShortcut(QKeySequence("Esc"))
        close.triggered.connect(dlg.reject)
        dlg.addAction(close)
        dlg.exec()

    # ----- data / actions -----

    def _refresh_header(self) -> None:
        mode = self.session.settings.mode().value.upper()
        callsign = self.session.settings.callsign() or "—"
        self.mode_chip.setText(f"MODE {mode}")
        self.callsign_chip.setText(f"FLT {callsign}")
        self.subtitle.setText(
            "Observer · print copy beside aircraft client"
            if self.session.settings.mode() == ClientMode.OBSERVER
            else "Station · poll, reply, print"
        )

    def _reload_messages(self) -> None:
        self.message_list.blockSignals(True)
        self.message_list.clear()
        rows = self.session.messages.list_recent(80)
        self._message_ids = [msg.id for msg in rows]
        if not rows:
            item = QListWidgetItem(
                "No traffic yet. Start monitoring or Check now."
            )
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
        needs = ""
        if (
            msg.direction == "in"
            and msg.message_type == MessageType.CPDLC.value
            and (msg.ra or "").upper() in {"WU", "AN", "R", "Y"}
        ):
            needs = " · REPLY"
        label = (
            f"{direction}  {msg.sender or msg.to_station or '?'}  "
            f"{msg.message_type.upper()}{needs}\n{preview}"
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
        self.detail_title.setText(
            f"{msg.message_type.upper()}  ·  {title_from or 'UNKNOWN'}"
        )
        meta_bits = [
            "INBOUND" if msg.direction == "in" else "OUTBOUND",
            f"FLT {msg.callsign}",
            f"#{msg.id}",
        ]
        if msg.min is not None:
            meta_bits.append(f"MIN {msg.min}")
        if msg.ra:
            meta_bits.append(f"RA {msg.ra}")
        if msg.send_status:
            meta_bits.append(msg.send_status.upper())
        self.detail_meta.setText("  ·  ".join(meta_bits))
        self.detail_body.setPlainText(msg.normalized_body)

    def _flash(self, text: str, *, error: bool = False) -> None:
        self.toast.setText(text)
        self.toast.setProperty("error", error)
        self.toast.style().unpolish(self.toast)
        self.toast.style().polish(self.toast)
        self.debug.toast(text, error=error)

    def _debug_context(self) -> dict[str, Any]:
        settings = self.session.settings
        mode = settings.mode().value
        return {
            "mode": mode,
            "hoppie_type": "peek" if mode == ClientMode.OBSERVER.value else "poll",
            "callsign": settings.callsign() or "-",
            "logon": mask_logon(settings.hoppie_logon()) or "-",
            "poll_interval": settings.poll_interval(),
            "printer": settings.printer_destination(),
            "running": getattr(self, "poller", None) is not None
            and self.poller.status.running,
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

    def _persist_mode_from_form(self) -> None:
        """Apply Mode combo even if the user forgot to click Save settings."""
        mode_widget = self._settings_widgets.get("mode")
        if mode_widget is None:
            return
        try:
            selected = ClientMode(mode_widget.currentText())
        except ValueError:
            return
        if self.session.settings.mode() != selected:
            previous = self.session.settings.mode().value
            self.session.settings.set_mode(selected)
            self.debug.info(
                "mode_autosaved",
                from_mode=previous,
                to_mode=selected.value,
            )
            self._refresh_header()

    def _start_poller(self) -> None:
        self._persist_mode_from_form()
        if not self.session.settings.callsign() or not self.session.settings.hoppie_logon():
            self._flash("Set callsign and logon in Settings first.", error=True)
            self.tabs.setCurrentIndex(2)
            return
        mode = self.session.settings.mode().value
        self.poller.start()
        self.link_chip.setText("LINK live")
        self.link_chip.setStyleSheet(f"color: {COLORS['ok']};")
        op = "peek" if mode == ClientMode.OBSERVER.value else "poll"
        self._flash(f"Monitoring started ({mode} / {op}).")

    def _stop_poller(self) -> None:
        self.poller.stop()
        self.link_chip.setText("LINK paused")
        self.link_chip.setStyleSheet(f"color: {COLORS['muted']};")
        self._flash("Monitoring paused.")

    def _check_now(self) -> None:
        self._persist_mode_from_form()
        if not self.poller.status.running:
            self.poller.start()
        self.poller.check_now()
        mode = self.session.settings.mode().value
        op = "peek" if mode == ClientMode.OBSERVER.value else "poll"
        self._flash(f"Check requested ({mode} / {op})…")

    @Slot(object)
    def _apply_poller_update(self, status: object) -> None:
        if self._closing or not isinstance(status, PollerStatus):
            return
        stats = status.last_stats or {}
        fields = {
            **self._debug_context(),
            "last_mode": status.last_mode or "-",
            "last_hoppie_type": status.last_hoppie_type or "-",
            "callsign_in_use": status.callsign_in_use,
            "printed": stats.get("printed", 0),
            "stored": stats.get("stored", 0),
            "duplicates": stats.get("duplicates", 0),
        }
        if status.last_error:
            self.debug.error("poller", message=status.last_error, **fields)
        else:
            self.debug.info("poller", **fields)
        if status.last_check:
            color = COLORS["ok"] if not status.last_error else COLORS["warn"]
            self.link_chip.setText(f"LINK {status.last_check.strftime('%H:%MZ')}")
            self.link_chip.setStyleSheet(f"color: {color};")
        if status.callsign_in_use:
            self._flash(status.last_error or "Callsign in use.", error=True)
        elif status.last_error:
            self._flash(status.last_error, error=True)
        elif status.last_stats:
            s = status.last_stats
            self._flash(
                f"Check ok · new {s.get('printed', 0) + s.get('stored', 0)} · "
                f"dup {s.get('duplicates', 0)}"
            )
        self._reload_messages()

    @Slot(int)
    def _on_new_messages(self, count: int) -> None:
        notify("ACARS Print Bridge", f"{count} new message(s)")

    def _reply(self, reply: str) -> None:
        if self._selected_id is None:
            self._flash("Select an inbound CPDLC message first.", error=True)
            return
        try:
            stored = self.session.outbound.reply_cpdlc(self._selected_id, reply)
            self._flash(f"Sent {stored.normalized_body} → {stored.to_station}")
            self.poller.check_now()
            self._reload_messages()
        except (HoppieError, SendNotAllowedError) as exc:
            self._flash(str(exc), error=True)

    def _send_telex(self) -> None:
        to = self.telex_to.text().strip()
        text = self.telex_body.text().strip()
        if not to or not text:
            self._flash("Telex needs TO and message text.", error=True)
            return
        try:
            stored = self.session.outbound.send_telex(to, text)
            self.telex_body.clear()
            self._flash(f"Telex #{stored.id} sent to {stored.to_station}")
            self.poller.check_now()
            self._reload_messages()
        except (HoppieError, SendNotAllowedError) as exc:
            self._flash(str(exc), error=True)

    def _request_metar(self) -> None:
        self._request_weather(WeatherKind.METAR)

    def _request_taf(self) -> None:
        self._request_weather(WeatherKind.TAF)

    def _request_weather(self, kind: WeatherKind) -> None:
        icao = self._request_widgets["icao"].text().strip()
        try:
            rows = self.session.outbound.request_weather(kind, icao)
            inbound = [r for r in rows if r.direction == "in"]
            if inbound:
                self._flash(f"{kind.value.upper()} {icao.upper()} · {len(inbound)} reply")
            else:
                self._flash(f"{kind.value.upper()} {icao.upper()} sent — empty reply")
            self._reload_messages()
            if inbound:
                self._select_message_id(inbound[0].id)
        except (HoppieError, SendNotAllowedError, ValueError) as exc:
            self._flash(str(exc), error=True)

    def _request_atis(self) -> None:
        w = self._request_widgets
        icao = w["icao"].text().strip()
        side = AtisSide(w["atis_side"].currentData())
        source = AtisSource(w["atis_source"].currentData())
        self.session.settings.set("req_atis_side", side.value)
        self.session.settings.set("req_atis_source", source.value)
        try:
            rows = self.session.outbound.request_atis(icao, source=source, side=side)
            inbound = [r for r in rows if r.direction == "in"]
            label = f"ATIS {icao.upper()} {side.value.upper()}"
            if inbound:
                self._flash(f"{label} · {len(inbound)} reply")
            else:
                self._flash(f"{label} sent — empty / offline")
            self._reload_messages()
            if inbound:
                self._select_message_id(inbound[0].id)
        except (HoppieError, SendNotAllowedError, ValueError) as exc:
            self._flash(str(exc), error=True)

    def _request_pdc(self) -> None:
        w = self._request_widgets
        try:
            stored = self.session.outbound.request_pdc(
                station=w["pdc_station"].text(),
                departure=w["pdc_dep"].text(),
                destination=w["pdc_dest"].text(),
                aircraft_type=w["pdc_type"].text(),
                stand=w["pdc_stand"].text(),
                atis_letter=w["pdc_atis"].text(),
            )
            self._flash(f"PDC sent → {stored.to_station}")
            self.poller.check_now()
            self._reload_messages()
        except (HoppieError, SendNotAllowedError, ValueError) as exc:
            self._flash(str(exc), error=True)

    def _send_position_report(self) -> None:
        w = self._request_widgets
        try:
            stored = self.session.outbound.send_position(
                to=w["pos_to"].text(),
                latitude=w["pos_lat"].text(),
                longitude=w["pos_lon"].text(),
                altitude=w["pos_alt"].text(),
                time_utc=w["pos_time"].text(),
                next_waypoint=w["pos_next"].text() or None,
                eta=w["pos_eta"].text() or None,
            )
            self._flash(f"Position sent → {stored.to_station}")
            self.poller.check_now()
            self._reload_messages()
        except (HoppieError, SendNotAllowedError, ValueError) as exc:
            self._flash(str(exc), error=True)

    def _select_message_id(self, message_id: int) -> None:
        try:
            row = self._message_ids.index(message_id)
        except ValueError:
            return
        self.message_list.setCurrentRow(row)

    def _reprint(self) -> None:
        if self._selected_id is None:
            self._flash("Select a message to print.", error=True)
            return
        msg = self.session.messages.get(self._selected_id)
        if not msg:
            return
        settings = PrinterSettings(
            destination=self.session.settings.printer_destination(),
            paper_width=self.session.settings.paper_width(),
            cut_enabled=self.session.settings.cut_enabled(),
        )
        result = self.session.print_manager.print_message(msg, settings, is_reprint=True)
        ok = result == "printed"
        self._flash("Printed." if ok else "Print failed.", error=not ok)

    def _test_print(self) -> None:
        settings = PrinterSettings(
            destination=self.session.settings.printer_destination(),
            paper_width=self.session.settings.paper_width(),
            cut_enabled=self.session.settings.cut_enabled(),
        )
        try:
            self.session.print_manager.test_print(settings)
            self._flash(f"Test print → {settings.destination}")
        except Exception as exc:  # noqa: BLE001
            self._flash(f"Test print failed: {exc}", error=True)

    def _save_settings(self) -> None:
        w = self._settings_widgets
        callsign = w["callsign"].text().strip()
        if callsign:
            self.session.settings.set_callsign(callsign)
        logon = w["logon"].text().strip()
        if logon:
            self.session.settings.set_hoppie_logon(logon)
        self.session.settings.set_mode(ClientMode(w["mode"].currentText()))
        printer_label = w["printer"].currentText().strip() or "console"
        self.session.settings.set_printer_destination(
            destination_from_label(printer_label, self._printer_choices)
        )
        self.session.settings.set_paper_width(w["width"].currentText())
        self.session.settings.set_auto_print(w["auto_print"].currentText() == "on")
        scale_value = {"85%": 0.85, "100%": 1.0, "115%": 1.15, "125%": 1.25}.get(
            w["ui_scale"].currentText(), 1.0
        )
        prev_scale = self.session.settings.ui_scale()
        self.session.settings.set_ui_scale(scale_value)
        try:
            interval = int(w["interval"].text())
            self.session.settings.set("poll_interval", str(max(45, interval)))
        except ValueError:
            pass
        self.session.rebuild_printer()
        self._refresh_header()
        if abs(prev_scale - scale_value) > 0.001:
            app = QApplication.instance()
            if isinstance(app, QApplication):
                apply_theme(app, ui_scale=scale_value)
            self._flash("Settings saved. UI scale applied.")
        else:
            self._flash("Settings saved.")
        self.tabs.setCurrentIndex(0)

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
            "Actions, toasts, and Hoppie poll/peek results are logged here "
            "(logon is masked). Copy and paste into chat, or open the file."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        path_label = QLabel(str(self.debug.path))
        path_label.setObjectName("Muted")
        path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
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
            "poller_last_mode": self.poller.status.last_mode or "-",
            "poller_last_type": self.poller.status.last_hoppie_type or "-",
            "poller_last_error": self.poller.status.last_error or "-",
        }

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._closing = True
        self.debug.info("app_closing", **self._debug_context())
        self._clock_timer.stop()
        self._hotkeys.stop()
        self.poller.stop()
        self.session.close()
        super().closeEvent(event)


def run_app(paths: AppPaths | None = None) -> None:
    import sys

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    assert isinstance(app, QApplication)

    session = build_session(paths)
    apply_theme(app, ui_scale=session.settings.ui_scale())
    window = AcarsBridgeApp(session)
    window.show()
    app.exec()
