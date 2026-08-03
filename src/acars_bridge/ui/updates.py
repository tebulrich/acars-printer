"""Update-available dialog and background GitHub check / download workers."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from acars_bridge import __version__
from acars_bridge.services.updater import (
    ReleaseInfo,
    UpdateError,
    check_for_update,
    current_executable,
    download_release,
    is_frozen_app,
    schedule_windows_replace_and_restart,
)


class UpdateCheckWorker(QObject):
    finished = Signal(object)  # ReleaseInfo | None
    failed = Signal(str)

    def __init__(self, *, skipped_version: str | None) -> None:
        super().__init__()
        self._skipped = skipped_version

    @Slot()
    def run(self) -> None:
        try:
            release = check_for_update(skipped_version=self._skipped)
            self.finished.emit(release)
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class UpdateDownloadWorker(QObject):
    progress = Signal(int, int)
    finished = Signal(object)  # Path
    failed = Signal(str)

    def __init__(self, release: ReleaseInfo, dest_dir: Path) -> None:
        super().__init__()
        self._release = release
        self._dest_dir = dest_dir

    @Slot()
    def run(self) -> None:
        try:
            path = download_release(
                self._release,
                self._dest_dir,
                on_progress=lambda done, total: self.progress.emit(done, total),
            )
            self.finished.emit(path)
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    skipped = Signal(str)
    install_requested = Signal(object)  # ReleaseInfo

    def __init__(self, release: ReleaseInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._release = release
        self.setWindowTitle("Update available")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)

        title = QLabel(
            f"ACARS Print Bridge <b>{release.version}</b> is available "
            f"(you have {__version__})."
        )
        title.setWordWrap(True)
        layout.addWidget(title)

        notes = QTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(release.body or "(No release notes.)")
        notes.setMinimumHeight(160)
        layout.addWidget(notes)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        row = QHBoxLayout()
        self.btn_update = QPushButton("Download & install")
        self.btn_update.setObjectName("Primary")
        self.btn_later = QPushButton("Later")
        self.btn_skip = QPushButton("Skip this version")
        self.btn_notes = QPushButton("Open on GitHub")
        row.addWidget(self.btn_update)
        row.addWidget(self.btn_later)
        row.addWidget(self.btn_skip)
        row.addStretch(1)
        row.addWidget(self.btn_notes)
        layout.addLayout(row)

        can_install = is_frozen_app() and current_executable() is not None
        if not can_install:
            self.btn_update.setText("Open download page")
            self.status.setText(
                "Automatic install works from the Windows release .exe. "
                "From source, use the GitHub download page."
            )

        self.btn_update.clicked.connect(self._on_update)
        self.btn_later.clicked.connect(self.reject)
        self.btn_skip.clicked.connect(self._on_skip)
        self.btn_notes.clicked.connect(self._open_github)

    def _on_skip(self) -> None:
        self.skipped.emit(self._release.version)
        self.reject()

    def _open_github(self) -> None:
        if self._release.html_url:
            QDesktopServices.openUrl(self._release.html_url)

    def _on_update(self) -> None:
        if not (is_frozen_app() and current_executable() is not None):
            self._open_github()
            self.accept()
            return
        self.install_requested.emit(self._release)

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.btn_update.setEnabled(not busy)
        self.btn_later.setEnabled(not busy)
        self.btn_skip.setEnabled(not busy)
        self.progress.setVisible(busy)
        if message:
            self.status.setText(message)

    def set_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            mb = done / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            self.status.setText(f"Downloading… {mb:.1f} / {total_mb:.1f} MB")
        else:
            self.progress.setRange(0, 0)
            self.status.setText(f"Downloading… {done // 1024} KB")


class UpdateController(QObject):
    """Owns background threads for check + install; shows the dialog when needed."""

    def __init__(self, window: QWidget, session) -> None:
        super().__init__(window)
        self._window = window
        self._session = session
        self._dialog: UpdateDialog | None = None
        self._check_thread: QThread | None = None
        self._check_worker: UpdateCheckWorker | None = None
        self._download_thread: QThread | None = None
        self._download_worker: UpdateDownloadWorker | None = None
        self._manual = False

    def check(self, *, manual: bool = False) -> None:
        if self._check_thread is not None and self._check_thread.isRunning():
            if manual:
                self._notify("Already checking for updates…")
            return
        self._manual = manual
        if manual:
            self._notify("Checking for updates…")

        # Manual checks ignore "skip this version"; auto-check honors it.
        skipped = None if manual else self._session.settings.skipped_update_version()
        thread = QThread(self)
        worker = UpdateCheckWorker(skipped_version=skipped)
        # Keep a Python reference — otherwise GC can collect the worker before run().
        self._check_thread = thread
        self._check_worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(
            self._on_check_finished, Qt.ConnectionType.QueuedConnection
        )
        worker.failed.connect(
            self._on_check_failed, Qt.ConnectionType.QueuedConnection
        )
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_check_thread)
        thread.start()

    def _notify(self, text: str, *, error: bool = False) -> None:
        flash = getattr(self._window, "_flash", None)
        if callable(flash):
            flash(text, error=error)

    @Slot()
    def _clear_check_thread(self) -> None:
        self._check_thread = None
        self._check_worker = None

    @Slot(object)
    def _on_check_finished(self, release: object) -> None:
        if not isinstance(release, ReleaseInfo):
            if self._manual:
                QMessageBox.information(
                    self._window,
                    "Up to date",
                    f"You already have the latest version ({__version__}).",
                )
            return
        self._show_dialog(release)

    @Slot(str)
    def _on_check_failed(self, message: str) -> None:
        # Always surface failures — silent auto-check made it look broken.
        if self._manual:
            QMessageBox.warning(self._window, "Update check failed", message)
        else:
            self._notify(f"Update check failed: {message}", error=True)

    def _show_dialog(self, release: ReleaseInfo) -> None:
        if self._dialog is not None and self._dialog.isVisible():
            return
        dialog = UpdateDialog(release, self._window)
        dialog.skipped.connect(self._skip_version)
        dialog.install_requested.connect(self._start_install)
        self._dialog = dialog
        dialog.exec()
        self._dialog = None

    @Slot(str)
    def _skip_version(self, version: str) -> None:
        self._session.settings.set_skipped_update_version(version)

    @Slot(object)
    def _start_install(self, release: object) -> None:
        if not isinstance(release, ReleaseInfo) or self._dialog is None:
            return
        if self._download_thread is not None and self._download_thread.isRunning():
            return
        dest = self._session.paths.root / "updates"
        self._dialog.set_busy(True, "Downloading…")
        thread = QThread(self)
        worker = UpdateDownloadWorker(release, dest)
        self._download_thread = thread
        self._download_worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(
            self._on_download_progress, Qt.ConnectionType.QueuedConnection
        )
        worker.finished.connect(
            self._on_download_finished, Qt.ConnectionType.QueuedConnection
        )
        worker.failed.connect(
            self._on_download_failed, Qt.ConnectionType.QueuedConnection
        )
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_download_thread)
        thread.start()

    @Slot()
    def _clear_download_thread(self) -> None:
        self._download_thread = None
        self._download_worker = None

    @Slot(int, int)
    def _on_download_progress(self, done: int, total: int) -> None:
        if self._dialog is not None:
            self._dialog.set_progress(done, total)

    @Slot(object)
    def _on_download_finished(self, path: object) -> None:
        exe = current_executable()
        if self._dialog is None or not isinstance(path, Path) or exe is None:
            return
        try:
            self._dialog.set_busy(True, "Installing… the app will restart.")
            schedule_windows_replace_and_restart(new_exe=path, current_exe=exe)
        except UpdateError as exc:
            self._dialog.set_busy(False, "")
            QMessageBox.warning(self._window, "Install failed", str(exc))
            return
        # Ask the main window to quit for real (not tray).
        quit_fn = getattr(self._window, "_quit_from_tray", None)
        if callable(quit_fn):
            quit_fn()
        else:
            self._dialog.accept()
            self._window.close()

    @Slot(str)
    def _on_download_failed(self, message: str) -> None:
        if self._dialog is not None:
            self._dialog.set_busy(False, "")
        QMessageBox.warning(self._window, "Download failed", message)
