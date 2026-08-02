from __future__ import annotations

import sys


def notify(title: str, message: str) -> None:
    """Best-effort desktop notification; never raises into the UI loop."""
    try:
        if sys.platform.startswith("win"):
            _notify_windows(title, message)
        else:
            _notify_freedesktop(title, message)
    except Exception:
        pass


def _notify_windows(title: str, message: str) -> None:
    try:
        from win10toast import ToastNotifier  # type: ignore

        ToastNotifier().show_toast(title, message, duration=5, threaded=True)
        return
    except Exception:
        pass
    # Fallback: no-op if toast libs unavailable.


def _notify_freedesktop(title: str, message: str) -> None:
    import subprocess

    subprocess.run(
        ["notify-send", title, message],
        check=False,
        capture_output=True,
        timeout=3,
    )
