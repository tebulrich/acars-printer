from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from acars_bridge.hoppie.types import HoppieMessage, MessageType
from acars_bridge.models.db import Database


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class StoredMessage:
    id: int
    fingerprint: str | None
    direction: str
    callsign: str
    sender: str | None
    recipient: str | None
    to_station: str | None
    message_type: str
    raw_payload: str
    normalized_body: str
    min: int | None
    mrn: int | None
    ra: str | None
    send_status: str | None
    received_at: str

    @classmethod
    def from_row(cls, row: Any) -> StoredMessage:
        return cls(
            id=row["id"],
            fingerprint=row["fingerprint"],
            direction=row["direction"],
            callsign=row["callsign"],
            sender=row["sender"],
            recipient=row["recipient"],
            to_station=row["to_station"],
            message_type=row["message_type"],
            raw_payload=row["raw_payload"],
            normalized_body=row["normalized_body"],
            min=row["min"],
            mrn=row["mrn"],
            ra=row["ra"],
            send_status=row["send_status"],
            received_at=row["received_at"],
        )


class MessageRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def insert_inbound(self, message: HoppieMessage, fingerprint: str) -> StoredMessage | None:
        with self._db.lock:
            try:
                cur = self._db.conn.execute(
                    """
                    INSERT INTO messages (
                        fingerprint, direction, callsign, sender, recipient, to_station,
                        message_type, raw_payload, normalized_body, min, mrn, ra,
                        send_status, received_at
                    ) VALUES (?, 'in', ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (
                        fingerprint,
                        message.callsign,
                        message.sender,
                        message.recipient,
                        message.message_type.value,
                        message.raw_payload,
                        message.normalized_body,
                        message.min,
                        message.mrn,
                        message.ra,
                        _utc_now(),
                    ),
                )
                self._db.conn.commit()
                row_id = int(cur.lastrowid)
            except sqlite3.IntegrityError:
                self._db.conn.rollback()
                return None
        return self.get(row_id)

    def insert_outbound(
        self,
        *,
        callsign: str,
        to_station: str,
        message_type: MessageType,
        body: str,
        raw_payload: str,
        min_id: int | None = None,
        mrn: int | None = None,
        ra: str | None = None,
        send_status: str = "sent",
    ) -> StoredMessage:
        with self._db.lock:
            cur = self._db.conn.execute(
                """
                INSERT INTO messages (
                    fingerprint, direction, callsign, sender, recipient, to_station,
                    message_type, raw_payload, normalized_body, min, mrn, ra,
                    send_status, received_at
                ) VALUES (NULL, 'out', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    callsign,
                    callsign,
                    to_station,
                    to_station,
                    message_type.value,
                    raw_payload,
                    body,
                    min_id,
                    mrn,
                    ra,
                    send_status,
                    _utc_now(),
                ),
            )
            self._db.conn.commit()
            row_id = int(cur.lastrowid)
        stored = self.get(row_id)
        assert stored is not None
        return stored

    def get(self, message_id: int) -> StoredMessage | None:
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
        return StoredMessage.from_row(row) if row else None

    def list_recent(self, limit: int = 20) -> list[StoredMessage]:
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [StoredMessage.from_row(row) for row in rows]

    def create_print_job(
        self,
        message_id: int,
        printer_name: str,
        status: str,
        *,
        attempts: int = 1,
        error_message: str | None = None,
        is_reprint: bool = False,
    ) -> int:
        printed_at = _utc_now() if status == "printed" else None
        with self._db.lock:
            cur = self._db.conn.execute(
                """
                INSERT INTO print_jobs (
                    message_id, printer_name, status, attempts, error_message,
                    is_reprint, printed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    printer_name,
                    status,
                    attempts,
                    error_message,
                    1 if is_reprint else 0,
                    printed_at,
                ),
            )
            self._db.conn.commit()
            return int(cur.lastrowid)
