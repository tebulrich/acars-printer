from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ClientMode(StrEnum):
    STATION = "station"
    OBSERVER = "observer"


class MessageType(StrEnum):
    CPDLC = "cpdlc"
    TELEX = "telex"
    PROGRESS = "progress"
    POSITION = "position"
    POSREQ = "posreq"
    PING = "ping"
    DATAREQ = "datareq"
    INFOREQ = "inforeq"
    UNKNOWN = "unknown"

    @classmethod
    def from_hoppie(cls, value: str) -> MessageType:
        normalized = value.strip().lower()
        # Inline weather/ATIS replies often use type "info".
        if normalized == "info":
            return cls.INFOREQ
        try:
            return cls(normalized)
        except ValueError:
            return cls.UNKNOWN

    def label(self) -> str:
        return {
            MessageType.CPDLC: "CPDLC UPLINK",
            MessageType.TELEX: "TELEX",
            MessageType.PROGRESS: "PROGRESS",
            MessageType.POSITION: "POSITION",
            MessageType.POSREQ: "POSREQ",
            MessageType.PING: "PING",
            MessageType.DATAREQ: "DATAREQ",
            MessageType.INFOREQ: "INFOREQ",
            MessageType.UNKNOWN: "UNKNOWN",
        }[self]


@dataclass(frozen=True, slots=True)
class HoppieMessage:
    callsign: str
    sender: str | None
    recipient: str | None
    message_type: MessageType
    raw_payload: str
    normalized_body: str
    min: int | None = None
    mrn: int | None = None
    ra: str | None = None
