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
