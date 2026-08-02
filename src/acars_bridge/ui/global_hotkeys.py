from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from acars_bridge.ui.hotkeys import HotkeyBindingError, qt_to_pynput, validate_bindings

log = logging.getLogger(__name__)


class GlobalHotkeyManager(QObject):
    """
    System-wide hotkeys via pynput, marshalled onto the Qt UI thread.

    Bindings are unset by default; only explicitly configured actions are registered.
    """

    activated = Signal(str)  # action id
    status_changed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._listener = None
        self._bindings: dict[str, str] = {}
        self._action_for_pynput: dict[str, str] = {}

    @property
    def bindings(self) -> dict[str, str]:
        return dict(self._bindings)

    def set_bindings(self, bindings: dict[str, str]) -> None:
        """Replace registered global hotkeys. Empty dict clears all."""
        cleaned = {action: seq for action, seq in bindings.items() if seq}
        if cleaned:
            validate_bindings(cleaned)
        self._bindings = cleaned
        self._restart_listener()

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        self._action_for_pynput.clear()
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass

    def _restart_listener(self) -> None:
        self.stop()
        if not self._bindings:
            self.status_changed.emit("No global shortcuts configured.")
            return

        mapping: dict[str, Callable[[], None]] = {}
        action_for: dict[str, str] = {}
        failed: list[str] = []
        for action, seq in self._bindings.items():
            try:
                pynput_seq = qt_to_pynput(seq)
            except HotkeyBindingError as exc:
                failed.append(f"{action}: {exc}")
                continue

            def make_cb(act: str = action) -> Callable[[], None]:
                def _cb() -> None:
                    self.activated.emit(act)

                return _cb

            mapping[pynput_seq] = make_cb()
            action_for[pynput_seq] = action

        if not mapping:
            self.status_changed.emit("No usable global shortcuts.")
            return

        try:
            from pynput import keyboard
        except ImportError as exc:
            self.status_changed.emit(f"Global hotkeys unavailable: {exc}")
            return

        try:
            listener = keyboard.GlobalHotKeys(mapping)
            listener.start()
        except Exception as exc:
            log.warning("Failed to start global hotkeys: %s", exc)
            self.status_changed.emit(f"Global hotkeys failed: {exc}")
            return

        self._listener = listener
        self._action_for_pynput = action_for
        msg = f"Global shortcuts active: {len(mapping)}"
        if failed:
            msg += f" · skipped {len(failed)}"
        self.status_changed.emit(msg)

    @Slot()
    def shutdown(self) -> None:
        self.stop()
