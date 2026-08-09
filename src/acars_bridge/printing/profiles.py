"""Named POS / thermal format profiles (builtins + user-saved)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class _FormatSettings(Protocol):
    def paper_width(self) -> str: ...
    def cut_enabled(self) -> bool: ...
    def print_font(self) -> str: ...
    def print_bold(self) -> bool: ...
    def print_render_mode(self) -> str: ...
    def print_char_width(self) -> int: ...
    def print_char_height(self) -> int: ...
    def print_line_spacing_dots(self) -> int | None: ...
    def print_glyph_px(self) -> int: ...
    def print_line_gap_px(self) -> int: ...
    def print_columns(self) -> int | None: ...
    def print_lead_in(self) -> int: ...
    def print_tear_feed(self) -> int: ...


@dataclass(frozen=True, slots=True)
class PrintProfile:
    id: str
    label: str
    builtin: bool
    payload: dict[str, Any]


# Stable ids for built-ins (user profiles use their display name as id).
BUILTIN_PROFILE_IDS: tuple[str, ...] = (
    "pos80_default",
    "pos58_readable",
    "pos80_compact",
)

_BUILTIN_LABELS: dict[str, str] = {
    "pos80_default": "POS-80 default",
    "pos58_readable": "POS-58 readable",
    "pos80_compact": "POS-80 compact",
}


def _base_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "paper_width": "80",
        "cut_enabled": True,
        "print_font": "a",
        "print_bold": False,
        "print_render_mode": "bitmap",
        "print_char_width": 1,
        "print_char_height": 1,
        "print_line_spacing_dots": None,
        "print_glyph_px": 28,
        "print_line_gap_px": 2,
        "print_columns": None,
        "print_lead_in": 2,
        "print_tear_feed": 6,
    }
    base.update(overrides)
    return base


def builtin_profiles() -> tuple[PrintProfile, ...]:
    """Shipping presets for common 58/80 mm ESC/POS quirks."""
    specs: list[tuple[str, dict[str, Any]]] = [
        ("pos80_default", _base_payload()),
        (
            "pos58_readable",
            _base_payload(
                paper_width="58",
                print_glyph_px=26,
                print_line_gap_px=1,
                print_lead_in=1,
                print_tear_feed=5,
            ),
        ),
        (
            "pos80_compact",
            _base_payload(
                print_glyph_px=22,
                print_line_gap_px=1,
                print_lead_in=1,
                print_tear_feed=4,
            ),
        ),
    ]
    return tuple(
        PrintProfile(
            id=pid,
            label=_BUILTIN_LABELS[pid],
            builtin=True,
            payload=payload,
        )
        for pid, payload in specs
    )


def profile_payload_from_settings(settings: _FormatSettings) -> dict[str, Any]:
    """Snapshot live format knobs (not printer destination)."""
    spacing = settings.print_line_spacing_dots()
    return {
        "paper_width": settings.paper_width(),
        "cut_enabled": bool(settings.cut_enabled()),
        "print_font": settings.print_font(),
        "print_bold": bool(settings.print_bold()),
        "print_render_mode": settings.print_render_mode(),
        "print_char_width": int(settings.print_char_width()),
        "print_char_height": int(settings.print_char_height()),
        "print_line_spacing_dots": spacing,
        "print_glyph_px": int(settings.print_glyph_px()),
        "print_line_gap_px": int(settings.print_line_gap_px()),
        "print_columns": settings.print_columns(),
        "print_lead_in": int(settings.print_lead_in()),
        "print_tear_feed": int(settings.print_tear_feed()),
    }


def normalize_profile_name(name: str) -> str:
    cleaned = " ".join(str(name or "").strip().split())
    if not cleaned:
        raise ValueError("Profile name is required")
    if len(cleaned) > 48:
        raise ValueError("Profile name is too long (max 48 characters)")
    lowered = cleaned.lower()
    if lowered in {p.id for p in builtin_profiles()} or lowered in {
        p.label.lower() for p in builtin_profiles()
    }:
        raise ValueError("That name is reserved for a built-in profile")
    return cleaned


def sanitize_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Clamp / normalize a stored profile dict."""
    paper = str(raw.get("paper_width", "80") or "80")
    paper = "58" if paper == "58" else "80"
    font = str(raw.get("print_font", "a") or "a").strip().lower()
    font = "b" if font == "b" else "a"
    mode = str(raw.get("print_render_mode", "bitmap") or "bitmap").strip().lower()
    mode = "native" if mode == "native" else "bitmap"

    def _int(key: str, default: int, lo: int, hi: int) -> int:
        try:
            return max(lo, min(hi, int(raw.get(key, default))))
        except (TypeError, ValueError):
            return default

    spacing_raw = raw.get("print_line_spacing_dots", None)
    if spacing_raw in (None, "", "default", "auto", -1, "-1", 0, "0"):
        spacing: int | None = None
    else:
        try:
            spacing = max(1, min(255, int(spacing_raw)))
        except (TypeError, ValueError):
            spacing = None

    cols_raw = raw.get("print_columns", None)
    if cols_raw in (None, "", "auto", 0, "0"):
        columns: int | None = None
    else:
        try:
            columns = max(16, min(80, int(cols_raw)))
        except (TypeError, ValueError):
            columns = None

    return {
        "paper_width": paper,
        "cut_enabled": bool(raw.get("cut_enabled", True)),
        "print_font": font,
        "print_bold": bool(raw.get("print_bold", False)),
        "print_render_mode": mode,
        "print_char_width": _int("print_char_width", 1, 1, 8),
        "print_char_height": _int("print_char_height", 1, 1, 8),
        "print_line_spacing_dots": spacing,
        "print_glyph_px": _int("print_glyph_px", 28, 8, 64),
        "print_line_gap_px": _int("print_line_gap_px", 2, 0, 32),
        "print_columns": columns,
        "print_lead_in": _int("print_lead_in", 2, 0, 12),
        "print_tear_feed": _int("print_tear_feed", 6, 0, 16),
    }
