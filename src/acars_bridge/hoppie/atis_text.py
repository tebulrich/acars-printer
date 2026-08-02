from __future__ import annotations

import re

_STATION_RE = re.compile(
    r"\b(?:VATATIS|ATIS)\s+([A-Z]{4})(?:_[A-Z0-9]+)?\b",
    re.IGNORECASE,
)

# First line of a stored inforeq body when we prepended the plane's packet.
_REQ_LINE_RE = re.compile(
    r"^(VATATIS|METAR|TAF|SHORTTAF|SHORTFAF|ATIS)\b",
    re.IGNORECASE,
)


def atis_reply_unavailable(body: str) -> bool:
    """True for Hoppie stubs when a VATATIS/ATIS station has no text."""
    compact = " ".join((body or "").upper().split())
    # Strip a leading request label so matching still works.
    if "\n" in (body or ""):
        first, _, rest = body.partition("\n")
        if _REQ_LINE_RE.match(first.strip()):
            compact = " ".join(rest.upper().split())
    return (
        "ATIS IS NOT AVAILABLE" in compact
        or "NO VATSIM ATIS AVAILABLE" in compact
        or compact in {"NOT AVAILABLE", "NO ATIS AVAILABLE"}
    )


def vatatis_airport_key(body: str) -> str | None:
    """Group D/A fallbacks: ``VATATIS EDDF_D`` and ``VATATIS EDDF`` → ``EDDF``."""
    text = body or ""
    first = text.split("\n", 1)[0]
    match = _STATION_RE.search(first) or _STATION_RE.search(text)
    if not match:
        return None
    return match.group(1).upper()


def inforeq_request_label(body: str) -> str | None:
    """Return leading packet line (e.g. VATATIS EDDF) when present."""
    first, sep, _rest = (body or "").partition("\n")
    label = first.strip()
    if not sep or not label or not _REQ_LINE_RE.match(label):
        return None
    return label.upper()
