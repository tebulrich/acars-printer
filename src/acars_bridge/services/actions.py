from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from acars_bridge.printing.base import PrinterError

if TYPE_CHECKING:
    from acars_bridge.services.session import AppSession

AutoPrintMode = Literal["on", "off", "toggle"]


class ActionError(Exception):
    """User-facing failure for printer panel actions."""


class PrinterActions:
    """Shared action surface for UI buttons, hotkeys, and tray."""

    def __init__(self, session: AppSession) -> None:
        self._session = session

    def reprint_last(self) -> str:
        msg = self._session.messages.latest_successfully_printed()
        if msg is None:
            raise ActionError("No printed strip to reprint yet.")
        settings = self._session.settings.as_printer_settings()
        sterile = self._session.sterile

        result_holder = {"result": "printed"}

        def job() -> None:
            result_holder["result"] = self._session.print_manager.print_message(
                msg, settings, is_reprint=True
            )

        if sterile.run_or_defer_acars(job):
            return "deferred"
        return result_holder["result"]

    def toggle_auto_print(self) -> bool:
        return self.set_auto_print(not self._session.settings.auto_print())

    def set_auto_print(self, enabled: bool) -> bool:
        self._session.settings.set_auto_print(bool(enabled))
        return self._session.settings.auto_print()

    def apply_auto_print(self, mode: AutoPrintMode) -> bool:
        if mode == "toggle":
            return self.toggle_auto_print()
        if mode == "on":
            return self.set_auto_print(True)
        if mode == "off":
            return self.set_auto_print(False)
        raise ActionError(f"Unknown auto-print mode: {mode}")

    def test_print(self) -> None:
        settings = self._session.settings.as_printer_settings()
        try:
            self._session.print_manager.test_print(settings)
        except PrinterError as exc:
            raise ActionError(str(exc)) from exc

    def feed(self, lines: int | None = None) -> None:
        settings = self._session.settings.as_printer_settings()
        try:
            self._session.print_manager.feed(settings, lines=lines)
        except PrinterError as exc:
            raise ActionError(str(exc)) from exc
