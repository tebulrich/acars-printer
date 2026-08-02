from __future__ import annotations

import re
from dataclasses import dataclass

# Community /data2/ form used on Hoppie. Official CPDLC page is currently disabled.
_DATA2_RE = re.compile(
    r"^/data2/(?P<min>\d*)/(?P<mrn>\d*)/(?P<ra>[A-Za-z]*)/(?P<text>.*)$",
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class CpdlcPacket:
    min: int | None
    mrn: int | None
    ra: str
    text: str

    @property
    def display_text(self) -> str:
        return self.text.replace("@", "\n")

    def requires_reply(self) -> bool:
        return self.ra.upper() in {"WU", "AN", "R", "Y"}

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
        allowed = {"WILCO", "ROGER", "UNABLE", "STANDBY"}
        if text not in allowed:
            raise ValueError(f"Unsupported CPDLC reply {reply!r}; use one of {sorted(allowed)}")
        return cls(min=our_min, mrn=uplink_min, ra="N", text=text)
