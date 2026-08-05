from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from acars_bridge.config import DEFAULT_POLL_INTERVAL_SECONDS, HOPPIE_DEFAULT_URL
from acars_bridge.hoppie.types import ClientMode
from acars_bridge.models.db import Database


class SettingsStore:
    def __init__(self, db: Database, key_path: Path) -> None:
        self._db = db
        self._key_path = key_path
        self._fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        if self._key_path.exists():
            return self._key_path.read_bytes().strip()
        key = Fernet.generate_key()
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        self._key_path.write_bytes(key)
        try:
            self._key_path.chmod(0o600)
        except OSError:
            pass
        return key

    def get(self, key: str, default: str | None = None) -> str | None:
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return default
        return row["value"]

    def set(self, key: str, value: str | None) -> None:
        with self._db.lock:
            if value is None:
                self._db.conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                self._db.conn.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
            self._db.conn.commit()

    def hoppie_logon(self) -> str | None:
        encrypted = self.get("hoppie_logon")
        if not encrypted:
            return None
        try:
            return self._fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            return None

    def set_hoppie_logon(self, logon: str) -> None:
        token = self._fernet.encrypt(logon.encode("utf-8")).decode("utf-8")
        self.set("hoppie_logon", token)

    def callsign(self) -> str | None:
        value = self.get("callsign")
        return value.upper() if value else None

    def set_callsign(self, callsign: str) -> None:
        self.set("callsign", callsign.strip().upper())

    def aircraft_registration(self) -> str | None:
        """Tail number for ACARS hardcopy header (e.g. D-AIXX)."""
        value = self.get("aircraft_registration")
        return value.upper() if value else None

    def set_aircraft_registration(self, registration: str) -> None:
        cleaned = registration.strip().upper()
        self.set("aircraft_registration", cleaned or None)

    def mode(self) -> ClientMode:
        # Print-bridge is Observer-only (peek beside the aircraft client).
        return ClientMode.OBSERVER

    def set_mode(self, mode: ClientMode) -> None:
        # Ignore station; always persist observer.
        self.set("client_mode", ClientMode.OBSERVER.value)

    def hoppie_url(self) -> str:
        return self.get("hoppie_url", HOPPIE_DEFAULT_URL) or HOPPIE_DEFAULT_URL

    def poll_interval(self) -> int:
        raw = self.get("poll_interval", str(DEFAULT_POLL_INTERVAL_SECONDS))
        try:
            return max(45, int(raw or DEFAULT_POLL_INTERVAL_SECONDS))
        except ValueError:
            return DEFAULT_POLL_INTERVAL_SECONDS

    def auto_print(self) -> bool:
        return (self.get("auto_print", "1") or "1") in {"1", "true", "yes", "on"}

    def set_auto_print(self, enabled: bool) -> None:
        self.set("auto_print", "1" if enabled else "0")

    def auto_connect(self) -> bool:
        """Connect the Hoppie tap automatically when the UI starts."""
        return (self.get("auto_connect", "1") or "1") in {"1", "true", "yes", "on"}

    def set_auto_connect(self, enabled: bool) -> None:
        self.set("auto_connect", "1" if enabled else "0")

    def check_updates(self) -> bool:
        return (self.get("check_updates", "1") or "1") in {"1", "true", "yes", "on"}

    def set_check_updates(self, enabled: bool) -> None:
        self.set("check_updates", "1" if enabled else "0")

    def skipped_update_version(self) -> str | None:
        value = (self.get("skipped_update_version") or "").strip()
        return value or None

    def set_skipped_update_version(self, version: str | None) -> None:
        if not version:
            self.set("skipped_update_version", None)
        else:
            self.set("skipped_update_version", version.lstrip("vV").strip())

    def printer_destination(self) -> str:
        return self.get("printer_destination", "console") or "console"

    def set_printer_destination(self, destination: str) -> None:
        self.set("printer_destination", destination)

    def paper_width(self) -> str:
        value = self.get("paper_width", "80") or "80"
        return "58" if value == "58" else "80"

    def set_paper_width(self, width: str) -> None:
        self.set("paper_width", "58" if str(width) == "58" else "80")

    def ui_scale(self) -> float:
        """User multiplier on top of OS DPI (1.0 = system only)."""
        raw = self.get("ui_scale", "1.0")
        try:
            return max(0.85, min(1.5, float(raw or 1.0)))
        except ValueError:
            return 1.0

    def set_ui_scale(self, scale: float | str) -> None:
        try:
            value = float(scale)
        except (TypeError, ValueError):
            value = 1.0
        self.set("ui_scale", f"{max(0.85, min(1.5, value)):.2f}")

    def cut_enabled(self) -> bool:
        # Default on: thermal POS needs feed-to-tear-bar after each receipt.
        return (self.get("cut_enabled", "1") or "1") in {"1", "true", "yes", "on"}

    def set_cut_enabled(self, enabled: bool) -> None:
        self.set("cut_enabled", "1" if enabled else "0")

    def print_font(self) -> str:
        value = (self.get("print_font", "a") or "a").strip().lower()
        return "b" if value == "b" else "a"

    def set_print_font(self, font: str) -> None:
        self.set("print_font", "b" if str(font).strip().lower() == "b" else "a")

    def print_bold(self) -> bool:
        # Default off — bold Consolas on thermal looks too heavy vs airline strips.
        return (self.get("print_bold", "0") or "0") in {"1", "true", "yes", "on"}

    def set_print_bold(self, enabled: bool) -> None:
        self.set("print_bold", "1" if enabled else "0")

    def print_render_mode(self) -> str:
        value = (self.get("print_render_mode") or "").strip().lower()
        if value in {"bitmap", "native"}:
            return value
        # Default to exact pixel sizing — built-in fonts cannot go below 1×.
        return "bitmap"

    def set_print_render_mode(self, mode: str) -> None:
        value = str(mode).strip().lower()
        self.set("print_render_mode", "bitmap" if value == "bitmap" else "native")

    def print_char_width(self) -> int:
        raw = self.get("print_char_width")
        if raw is None:
            # Migrate old print_size presets.
            legacy = (self.get("print_size", "normal") or "normal").strip().lower()
            return 2 if legacy in {"wide", "large"} else 1
        try:
            return max(1, min(8, int(raw)))
        except ValueError:
            return 1

    def set_print_char_width(self, width: int | str) -> None:
        try:
            value = int(width)
        except (TypeError, ValueError):
            value = 1
        self.set("print_char_width", str(max(1, min(8, value))))

    def print_char_height(self) -> int:
        raw = self.get("print_char_height")
        if raw is None:
            legacy = (self.get("print_size", "normal") or "normal").strip().lower()
            return 2 if legacy in {"tall", "large"} else 1
        try:
            return max(1, min(8, int(raw)))
        except ValueError:
            return 1

    def set_print_char_height(self, height: int | str) -> None:
        try:
            value = int(height)
        except (TypeError, ValueError):
            value = 1
        self.set("print_char_height", str(max(1, min(8, value))))

    def print_line_spacing_dots(self) -> int | None:
        raw = self.get("print_line_spacing_dots")
        if raw is None:
            # Migrate old named presets.
            legacy = (self.get("print_line_spacing", "default") or "default").strip().lower()
            mapping = {"tight": 24, "normal": 30, "loose": 40}
            return mapping.get(legacy)
        value = str(raw).strip().lower()
        if value in {"", "default", "auto", "-1"}:
            return None
        try:
            dots = int(value)
        except ValueError:
            return None
        if dots <= 0:
            return None
        return max(1, min(255, dots))

    def set_print_line_spacing_dots(self, dots: int | str | None) -> None:
        if dots is None or str(dots).strip().lower() in {"", "default", "auto", "0", "-1"}:
            self.set("print_line_spacing_dots", "default")
            return
        try:
            value = int(dots)
        except (TypeError, ValueError):
            self.set("print_line_spacing_dots", "default")
            return
        if value <= 0:
            self.set("print_line_spacing_dots", "default")
        else:
            self.set("print_line_spacing_dots", str(max(1, min(255, value))))

    def print_glyph_px(self) -> int:
        raw = self.get("print_glyph_px", "28")
        try:
            return max(8, min(64, int(raw or 28)))
        except ValueError:
            return 28

    def set_print_glyph_px(self, px: int | str) -> None:
        try:
            value = int(px)
        except (TypeError, ValueError):
            value = 28
        self.set("print_glyph_px", str(max(8, min(64, value))))

    def print_line_gap_px(self) -> int:
        raw = self.get("print_line_gap_px", "2")
        try:
            return max(0, min(32, int(raw or 2)))
        except ValueError:
            return 2

    def set_print_line_gap_px(self, px: int | str) -> None:
        try:
            value = int(px)
        except (TypeError, ValueError):
            value = 2
        self.set("print_line_gap_px", str(max(0, min(32, value))))

    def print_columns(self) -> int | None:
        """Manual wrap width; None = auto from paper width + font."""
        raw = (self.get("print_columns") or "").strip()
        if not raw or raw.lower() in {"auto", "0"}:
            return None
        try:
            cols = int(raw)
        except ValueError:
            return None
        return max(16, min(80, cols))

    def set_print_columns(self, columns: int | str | None) -> None:
        if columns is None or str(columns).strip().lower() in {"", "auto", "0"}:
            self.set("print_columns", None)
            return
        try:
            cols = int(columns)
        except (TypeError, ValueError):
            self.set("print_columns", None)
            return
        self.set("print_columns", str(max(16, min(80, cols))))

    def print_lead_in(self) -> int:
        # ~2 lines ≈ 1.5 cm on a typical POS-80; 3 was closer to ~2 cm.
        raw = self.get("print_lead_in", "2")
        try:
            return max(0, min(12, int(raw or 2)))
        except ValueError:
            return 2

    def set_print_lead_in(self, lines: int | str) -> None:
        try:
            value = int(lines)
        except (TypeError, ValueError):
            value = 2
        self.set("print_lead_in", str(max(0, min(12, value))))

    def print_tear_feed(self) -> int:
        raw = self.get("print_tear_feed", "6")
        try:
            return max(0, min(16, int(raw or 6)))
        except ValueError:
            return 6

    def set_print_tear_feed(self, lines: int | str) -> None:
        try:
            value = int(lines)
        except (TypeError, ValueError):
            value = 6
        self.set("print_tear_feed", str(max(0, min(16, value))))

    def as_printer_settings(self, destination: str | None = None) -> "PrinterSettings":
        from acars_bridge.printing.base import PrinterSettings

        return PrinterSettings(
            destination=destination or self.printer_destination(),
            paper_width=self.paper_width(),
            cut_enabled=self.cut_enabled(),
            character_width_override=self.print_columns(),
            aircraft_registration=self.aircraft_registration(),
            font=self.print_font(),  # type: ignore[arg-type]
            bold=self.print_bold(),
            render_mode=self.print_render_mode(),  # type: ignore[arg-type]
            char_width=self.print_char_width(),
            char_height=self.print_char_height(),
            line_spacing_dots=self.print_line_spacing_dots(),
            glyph_px=self.print_glyph_px(),
            line_gap_px=self.print_line_gap_px(),
            lead_in_lines=self.print_lead_in(),
            tear_feed_lines=self.print_tear_feed(),
        )

    def printable_types(self) -> set[str]:
        raw = self.get("printable_types", "cpdlc,telex,inforeq") or "cpdlc,telex,inforeq"
        return {part.strip().lower() for part in raw.split(",") if part.strip()}

    def next_downlink_min(self) -> int:
        raw = self.get("next_downlink_min", "1") or "1"
        try:
            current = int(raw)
        except ValueError:
            current = 1
        self.set("next_downlink_min", str(current + 1))
        return current
