from __future__ import annotations

import re


def redact(text: str, logon: str | None = None) -> str:
    redacted = text
    if logon:
        redacted = redacted.replace(logon, "[REDACTED_LOGON]")
    redacted = re.sub(r"([?&]logon=)[^&\s]+", r"\1[REDACTED_LOGON]", redacted, flags=re.I)
    redacted = re.sub(
        r"\blogon[\"']?\s*[:=]\s*[\"']?[^\"'\s,&]+",
        "logon=[REDACTED_LOGON]",
        redacted,
        flags=re.I,
    )
    return redacted


def mask_logon(logon: str | None) -> str:
    if not logon:
        return ""
    if len(logon) <= 4:
        return "*" * len(logon)
    return f"{logon[:2]}{'*' * (len(logon) - 4)}{logon[-2:]}"
