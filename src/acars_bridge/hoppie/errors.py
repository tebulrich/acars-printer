from __future__ import annotations


class HoppieError(Exception):
    """Base Hoppie integration error."""


class CallsignInUseError(HoppieError):
    """Hoppie refused the request because another station holds the callsign lock."""


class SendNotAllowedError(HoppieError):
    """Raised when the active mode cannot send (Observer)."""
