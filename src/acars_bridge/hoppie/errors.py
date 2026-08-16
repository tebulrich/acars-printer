from __future__ import annotations


class HoppieError(Exception):
    """Base Hoppie integration error.

    ``hint`` is an optional next step for the phone UI — keep ``message`` to
    one short line so toasts stay readable.
    """

    def __init__(self, message: str = "", *, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


class CallsignInUseError(HoppieError):
    """Hoppie refused the request because another station holds the callsign lock."""


class SendNotAllowedError(HoppieError):
    """Raised when the active mode cannot send (Observer)."""
