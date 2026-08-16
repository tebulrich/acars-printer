from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_TCP_PORT = 9100


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


def tcp_printer_destination(host: str, port: object = None) -> str:
    """Build ``tcp://host:port`` for a raw ESC/POS LAN printer. Empty host → ``""``."""
    cleaned = (host or "").strip()
    if not cleaned:
        return ""
    try:
        parsed_port = int(port)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed_port = DEFAULT_TCP_PORT
    if parsed_port < 1 or parsed_port > 65535:
        parsed_port = DEFAULT_TCP_PORT
    return f"tcp://{cleaned}:{parsed_port}"


def parse_tcp_printer(destination: str) -> tuple[str, int] | None:
    """Return ``(host, port)`` for a ``tcp://`` destination."""
    raw = (destination or "").strip()
    if not raw.lower().startswith("tcp://"):
        return None
    parsed = urlparse(raw)
    host = (parsed.hostname or "").strip()
    if not host:
        return None
    port = int(parsed.port) if parsed.port else DEFAULT_TCP_PORT
    if port < 1 or port > 65535:
        port = DEFAULT_TCP_PORT
    return host, port


def unc_share_name(raw: str) -> str | None:
    """Return ``\\\\host\\share`` for a Windows UNC printer path, else None."""
    text = (raw or "").strip()
    if text.lower().startswith("win32://"):
        text = text[8:]
    unified = text.replace("/", "\\")
    if not unified.startswith("\\\\"):
        return None
    parts = [part for part in unified.split("\\") if part]
    if len(parts) < 2:
        return None
    return "\\\\" + "\\".join(parts)


def windows_share_path(destination: str) -> str | None:
    """Display form of a UNC destination (``\\\\host\\queue``), else None."""
    return unc_share_name(destination)


def normalize_printer_destination(raw: str) -> str:
    """Accept list URIs, raw ``tcp://``, or a typed ``\\\\host\\queue`` share."""
    text = (raw or "").strip()
    if not text or text.lower() in {"console", "console (log only)"}:
        return "console"
    share = unc_share_name(text)
    if share:
        return f"win32://{share}"
    if text.lower().startswith("win32://"):
        name = text[8:].strip()
        return f"win32://{name}" if name else "console"
    return text


def infer_printer_input_mode(destination: str) -> str:
    """``list``, ``ip`` (raw tcp://), or ``path`` (Windows UNC share)."""
    dest = normalize_printer_destination(destination or "")
    if parse_tcp_printer(dest):
        return "ip"
    if windows_share_path(dest):
        return "path"
    return "list"


def destination_from_manual_draft(draft: str, port: object = None) -> str:
    """Parse a typed share or host[:port] into a stored destination."""
    typed = (draft or "").strip()
    if not typed:
        return "console"
    share = unc_share_name(typed)
    if share:
        return f"win32://{share}"
    if typed.lower().startswith("tcp://"):
        return typed
    if "://" not in typed and not typed.startswith("\\") and "/" not in typed:
        if ":" in typed:
            host, _, port_text = typed.rpartition(":")
            if host.strip() and port_text.isdigit():
                return tcp_printer_destination(host, port_text)
        return tcp_printer_destination(typed, port)
    return normalize_printer_destination(typed)


def destination_for_system_printer(name: str) -> str:
    share = unc_share_name(name)
    if share:
        return f"win32://{share}"
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
            choices.append(PrinterChoice(name, destination_for_system_printer(name)))
    else:
        for name in list_cups_printer_names():
            choices.append(PrinterChoice(cups_driver_label(name), f"cups://{name}"))
            choices.append(PrinterChoice(cups_pos_label(name), f"cups-raw://{name}"))

    current = normalize_printer_destination(current or "")
    if current and current != "console" and current not in {c.destination for c in choices}:
        choices.append(PrinterChoice(label_for_destination(current), current))

    return choices


def destination_from_label(label: str, choices: list[PrinterChoice]) -> str:
    label = (label or "").strip()
    for choice in choices:
        if choice.label == label or choice.destination == label:
            return choice.destination
    if not label or label in {"console", "console (log only)"}:
        return "console"
    share = unc_share_name(label)
    if share:
        return f"win32://{share}"
    # Typed/custom URI pasted into an older UI, or unknown name.
    if "://" in label:
        return normalize_printer_destination(label)
    # Bare queue name → driver text (safe default for MFPs).
    return destination_for_system_printer(label)


def is_device_printer_destination(destination: str) -> bool:
    dest = normalize_printer_destination(destination)
    return dest.startswith(
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
