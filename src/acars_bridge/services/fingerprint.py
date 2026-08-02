from __future__ import annotations

import hashlib

from acars_bridge.hoppie.types import HoppieMessage


def fingerprint_for(message: HoppieMessage) -> str:
    if message.min is not None and message.message_type.value == "cpdlc":
        # Prefer stable CPDLC MIN + sender when available.
        basis = (
            f"cpdlc-min|{message.callsign}|{message.sender}|"
            f"{message.min}|{message.normalized_body}"
        )
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    body = _canonicalize_body(message.normalized_body)
    canonical = "|".join(
        [
            message.callsign.upper(),
            (message.sender or "").upper(),
            (message.recipient or "").upper(),
            message.message_type.value,
            "",
            body,
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonicalize_body(body: str) -> str:
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in body.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)
