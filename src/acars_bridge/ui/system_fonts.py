from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class SystemFontSpec:
    family: str
    file_path: str | None = None


def _run(cmd: list[str], *, timeout: float = 2.0) -> str:
    try:
        return subprocess.check_output(
            cmd, stderr=subprocess.DEVNULL, text=True, timeout=timeout
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _parse_gnome_font_name(raw: str) -> str | None:
    # gsettings returns: 'Inter Display 11' or "Ubuntu 11"
    value = raw.strip().strip("'\"")
    if not value:
        return None
    # Drop trailing size token(s): "Inter Display 11", "Jetbrains Mono 12"
    cleaned = re.sub(r"\s+\d+(?:\.\d+)?$", "", value).strip()
    return cleaned or None


def _fc_match_file(family: str) -> str | None:
    if not family:
        return None
    out = _run(["fc-match", "-f", "%{file}\n", family])
    path = out.splitlines()[0].strip() if out else ""
    return path if path and os.path.isfile(path) else None


def _fc_match_family(family: str) -> str | None:
    if not family:
        return None
    out = _run(["fc-match", "-f", "%{family}\n", family])
    resolved = out.splitlines()[0].strip() if out else ""
    # fc-match may return comma-separated aliases
    return resolved.split(",")[0].strip() if resolved else None


def linux_ui_font() -> SystemFontSpec | None:
    raw = _run(["gsettings", "get", "org.gnome.desktop.interface", "font-name"])
    family = _parse_gnome_font_name(raw)
    if not family:
        # Generic fontconfig UI face
        family = _fc_match_family("sans-serif")
    if not family:
        return None
    return SystemFontSpec(family=family, file_path=_fc_match_file(family))


def linux_mono_font() -> SystemFontSpec | None:
    raw = _run(["gsettings", "get", "org.gnome.desktop.interface", "monospace-font-name"])
    family = _parse_gnome_font_name(raw)
    if not family:
        family = _fc_match_family("monospace")
    if not family:
        return None
    return SystemFontSpec(family=family, file_path=_fc_match_file(family))


def windows_ui_font() -> SystemFontSpec | None:
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None

    # SPI_GETNONCLIENTMETRICS
    class LOGFONTW(ctypes.Structure):
        _fields_ = [
            ("lfHeight", wintypes.LONG),
            ("lfWidth", wintypes.LONG),
            ("lfEscapement", wintypes.LONG),
            ("lfOrientation", wintypes.LONG),
            ("lfWeight", wintypes.LONG),
            ("lfItalic", wintypes.BYTE),
            ("lfUnderline", wintypes.BYTE),
            ("lfStrikeOut", wintypes.BYTE),
            ("lfCharSet", wintypes.BYTE),
            ("lfOutPrecision", wintypes.BYTE),
            ("lfClipPrecision", wintypes.BYTE),
            ("lfQuality", wintypes.BYTE),
            ("lfPitchAndFamily", wintypes.BYTE),
            ("lfFaceName", wintypes.WCHAR * 32),
        ]

    class NONCLIENTMETRICSW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("iBorderWidth", ctypes.c_int),
            ("iScrollWidth", ctypes.c_int),
            ("iScrollHeight", ctypes.c_int),
            ("iCaptionWidth", ctypes.c_int),
            ("iCaptionHeight", ctypes.c_int),
            ("lfCaptionFont", LOGFONTW),
            ("iSmCaptionWidth", ctypes.c_int),
            ("iSmCaptionHeight", ctypes.c_int),
            ("lfSmCaptionFont", LOGFONTW),
            ("iMenuWidth", ctypes.c_int),
            ("iMenuHeight", ctypes.c_int),
            ("lfMenuFont", LOGFONTW),
            ("lfStatusFont", LOGFONTW),
            ("lfMessageFont", LOGFONTW),
            ("iPaddedBorderWidth", ctypes.c_int),
        ]

    metrics = NONCLIENTMETRICSW()
    metrics.cbSize = ctypes.sizeof(NONCLIENTMETRICSW)
    ok = ctypes.windll.user32.SystemParametersInfoW(
        0x0029, metrics.cbSize, ctypes.byref(metrics), 0
    )
    if not ok:
        return SystemFontSpec(family="Segoe UI")
    face = metrics.lfMessageFont.lfFaceName
    return SystemFontSpec(family=face or "Segoe UI")


def darwin_ui_font() -> SystemFontSpec | None:
    # SF Pro isn't always exposable by family name to Tk; Helvetica Neue is safe.
    return SystemFontSpec(family=".AppleSystemUIFont")


@lru_cache(maxsize=1)
def preferred_ui_font() -> SystemFontSpec:
    if sys.platform.startswith("win"):
        return windows_ui_font() or SystemFontSpec(family="Segoe UI")
    if sys.platform == "darwin":
        return darwin_ui_font() or SystemFontSpec(family="Helvetica Neue")
    return linux_ui_font() or SystemFontSpec(family="sans-serif")


@lru_cache(maxsize=1)
def preferred_mono_font() -> SystemFontSpec:
    if sys.platform.startswith("win"):
        return SystemFontSpec(family="Cascadia Mono")
    if sys.platform == "darwin":
        return SystemFontSpec(family="Menlo")
    return linux_mono_font() or SystemFontSpec(family="monospace")
