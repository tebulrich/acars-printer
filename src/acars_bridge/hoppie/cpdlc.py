from __future__ import annotations

import re
from dataclasses import dataclass

# Community /data2/ form used on Hoppie. Official CPDLC page is currently disabled.
_DATA2_RE = re.compile(
    r"^/data2/(?P<min>\d*)/(?P<mrn>\d*)/(?P<ra>[A-Za-z]*)/(?P<text>.*)$",
    re.DOTALL,
)


def expand_cpdlc_at_marks(text: str) -> str:
    """Turn Hoppie ``@`` markers into printable text for a thermal strip.

    Aircraft CDUs treat ``@`` as a wrap. VATSIM PDC also wraps fill-in values
    (``@EDDM@``, ``@18@``). Expanding every ``@`` to a newline prints one
    word per row. Use a space and let the formatter wrap at column width.
    ``@@`` stays a paragraph break.
    """
    if not text:
        return ""
    expanded = text.replace("@@", "\n").replace("@", " ")
    lines = [re.sub(r"[ \t]{2,}", " ", line).strip() for line in expanded.split("\n")]
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class CpdlcPacket:
    min: int | None
    mrn: int | None
    ra: str
    text: str

    @property
    def display_text(self) -> str:
        return expand_cpdlc_at_marks(self.text)

    def requires_reply(self) -> bool:
        return bool(reply_choices(self.ra))

    def encode(self) -> str:
        min_s = "" if self.min is None else str(self.min)
        mrn_s = "" if self.mrn is None else str(self.mrn)
        # Hoppie presentation uses @ as line breaks in CPDLC packets.
        wire_text = self.text.replace("\n", "@")
        return f"/data2/{min_s}/{mrn_s}/{self.ra}/{wire_text}"

    @classmethod
    def parse(cls, packet: str) -> CpdlcPacket:
        match = _DATA2_RE.match(packet.strip())
        if not match:
            raise ValueError(f"Not a /data2/ CPDLC packet: {packet!r}")
        min_raw = match.group("min")
        mrn_raw = match.group("mrn")
        return cls(
            min=int(min_raw) if min_raw != "" else None,
            mrn=int(mrn_raw) if mrn_raw != "" else None,
            ra=match.group("ra") or "",
            text=match.group("text"),
        )

    @classmethod
    def build_reply(
        cls,
        *,
        our_min: int,
        uplink_min: int | None,
        reply: str,
    ) -> CpdlcPacket:
        text = reply.strip().upper()
        allowed = {"WILCO", "ROGER", "UNABLE", "STANDBY", "AFFIRM", "NEGATIVE"}
        if text not in allowed:
            raise ValueError(
                f"Unsupported CPDLC reply {reply!r}; use one of {sorted(allowed)}"
            )
        return cls(min=our_min, mrn=uplink_min, ra="N", text=text)


def reply_choices(ra: str | None) -> list[str]:
    """Standard downlink replies for a Hoppie CPDLC RA code."""
    code = (ra or "").strip().upper()
    if code == "WU":
        return ["WILCO", "UNABLE", "STANDBY"]
    if code == "AN":
        return ["AFFIRM", "NEGATIVE", "STANDBY"]
    if code == "R":
        return ["ROGER", "STANDBY"]
    if code == "Y":
        return ["WILCO", "ROGER", "UNABLE", "STANDBY", "AFFIRM", "NEGATIVE"]
    return []
