from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PrinterChoice:
    """One selectable printer destination for Settings / CLI."""

    label: str
    destination: str


def _run(cmd: list[str], *, timeout: float = 3.0) -> str:
    try:
        return subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ""


def list_cups_printer_names() -> list[str]:
    """Installed CUPS queue names (Linux/macOS)."""
    # Prefer lpstat -e (one name per line on modern CUPS).
    names = [
        line.strip()
        for line in _run(["lpstat", "-e"]).splitlines()
        if line.strip()
    ]
    if names:
        return _unique(names)

    # Fallback: parse `lpstat -a` → "<name> accepting requests ..."
    parsed: list[str] = []
    for line in _run(["lpstat", "-a"]).splitlines():
        match = re.match(r"^(\S+)\s+accepting\b", line.strip())
        if match:
            parsed.append(match.group(1))
    return _unique(parsed)


def list_win32_printer_names() -> list[str]:
    """Installed Windows printers via win32print, when available."""
    if not sys.platform.startswith("win"):
        return []
    try:
        import win32print  # type: ignore[import-not-found]
    except ImportError:
        return []

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    try:
        printers = win32print.EnumPrinters(flags)
    except Exception:
        return []
    # EnumPrinters rows: (flags, description, name, comment) depending on level.
    names: list[str] = []
    for row in printers:
        if len(row) >= 3 and row[2]:
            names.append(str(row[2]))
    return _unique(names)


def destination_for_system_printer(name: str) -> str:
    if sys.platform.startswith("win"):
        return f"win32://{name}"
    return f"cups://{name}"


def cups_driver_label(name: str) -> str:
    return f"{name} · driver"


def cups_pos_label(name: str) -> str:
    return f"{name} · POS ESC/POS"


def label_for_destination(destination: str) -> str:
    if destination == "console" or not destination:
        return "console (log only)"
    if destination.startswith("cups-raw://"):
        return cups_pos_label(destination.removeprefix("cups-raw://"))
    if destination.startswith("cups://"):
        return cups_driver_label(destination.removeprefix("cups://"))
    if destination.startswith("win32://"):
        return destination.removeprefix("win32://")
    return destination


def list_printer_choices(current: str | None = None) -> list[PrinterChoice]:
    """
    Dropdown choices: console first, then installed system printers.

    On CUPS (Linux/macOS), each queue is listed twice:
    - ``Name · driver`` → ``cups://`` plain text for laser/inkjet/MFP
    - ``Name · POS ESC/POS`` → ``cups-raw://`` raw thermal / POS

    Preserves a custom current destination (tcp://, file://, …) if set.
    """
    choices: list[PrinterChoice] = [PrinterChoice("console (log only)", "console")]

    if sys.platform.startswith("win"):
        for name in list_win32_printer_names():
            choices.append(PrinterChoice(name, f"win32://{name}"))
    else:
        for name in list_cups_printer_names():
            choices.append(PrinterChoice(cups_driver_label(name), f"cups://{name}"))
            choices.append(PrinterChoice(cups_pos_label(name), f"cups-raw://{name}"))

    current = (current or "").strip()
    if current and current not in {c.destination for c in choices}:
        choices.append(PrinterChoice(label_for_destination(current), current))

    return choices


def destination_from_label(label: str, choices: list[PrinterChoice]) -> str:
    label = (label or "").strip()
    for choice in choices:
        if choice.label == label or choice.destination == label:
            return choice.destination
    if not label or label in {"console", "console (log only)"}:
        return "console"
    # Typed/custom URI pasted into an older UI, or unknown name.
    if "://" in label:
        return label
    # Bare queue name → driver text (safe default for MFPs).
    return destination_for_system_printer(label)


def is_device_printer_destination(destination: str) -> bool:
    return destination.startswith(
        ("tcp://", "file://", "win32://", "cups://", "cups-raw://")
    )


def _unique(names: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out
