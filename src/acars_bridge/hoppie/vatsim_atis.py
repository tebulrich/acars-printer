from __future__ import annotations

from dataclasses import dataclass

import httpx

from acars_bridge.hoppie.requests import AtisSide, AtisSource, normalize_icao

VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
VATSIM_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class VatsimAtis:
    callsign: str
    lines: list[str]
    atis_code: str | None = None

    @property
    def has_text(self) -> bool:
        return any(line.strip() for line in self.lines)

    def body(self) -> str:
        if self.has_text:
            return "\n".join(line.rstrip() for line in self.lines).strip()
        code = f" INFO {self.atis_code}" if self.atis_code else ""
        return f"{self.callsign}{code}\nNO ATIS TEXT PUBLISHED"


def list_vatsim_atis(
    icao: str,
    *,
    client: httpx.Client | None = None,
) -> list[VatsimAtis]:
    """All VATSIM ATIS rows for an airport ICAO."""
    code = normalize_icao(icao)
    owns_client = client is None
    http = client or httpx.Client(timeout=VATSIM_TIMEOUT_SECONDS)
    try:
        response = http.get(VATSIM_DATA_URL)
        response.raise_for_status()
        rows = response.json().get("atis", [])
    finally:
        if owns_client:
            http.close()

    matches = [
        hit
        for row in rows
        if (hit := _from_row(row)) is not None and hit.callsign.startswith(code)
    ]
    return matches


def fetch_vatsim_atis(
    icao: str,
    *,
    side: AtisSide | str | None = None,
    client: httpx.Client | None = None,
) -> VatsimAtis | None:
    """Best matching ATIS from the public VATSIM datafeed."""
    matches = list_vatsim_atis(icao, client=client)
    if not matches:
        return None

    from acars_bridge.hoppie.atis_pick import pick_network_atis

    return pick_network_atis(matches, icao=normalize_icao(icao), side=side)


def hoppie_vatatis_packets(
    icao: str,
    *,
    side: AtisSide | str | None = None,
    online_callsigns: set[str] | None = None,
) -> list[str]:
    """Hoppie ``vatatis`` packets to try, ordered for real VATSIM stations.

    Combined ``ICAO_ATIS`` always wins. Otherwise dep/arr when that split
    station is online. Plain ``vatatis ICAO`` is the fallback (Hoppie's
    combined resolver — verified EDDN/EDDS).
    """
    from acars_bridge.hoppie.atis_pick import is_combined_callsign, split_callsign

    code = normalize_icao(icao)
    online = {cs.upper() for cs in (online_callsigns or set())}
    packets: list[str] = []
    if any(is_combined_callsign(cs, code) for cs in online):
        packets.append(f"{AtisSource.VATSIM.value} {code}")
        packets.append(f"{AtisSource.VATSIM.value} {code}_ATIS")
        return _unique(packets)
    if side is not None:
        specific = split_callsign(code, side)
        if specific in online:
            packets.append(f"{AtisSource.VATSIM.value} {specific}")
    else:
        for letter in ("D", "A"):
            cs = f"{code}_{letter}_ATIS"
            if cs in online:
                packets.append(f"{AtisSource.VATSIM.value} {cs}")
    packets.append(f"{AtisSource.VATSIM.value} {code}")
    return _unique(packets)


def _from_row(row: dict) -> VatsimAtis | None:
    callsign = str(row.get("callsign", "")).strip().upper()
    if not callsign:
        return None
    raw = row.get("text_atis")
    lines: list[str] = []
    if isinstance(raw, list):
        lines = [str(part) for part in raw]
    elif isinstance(raw, str) and raw.strip():
        lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    code = row.get("atis_code")
    return VatsimAtis(
        callsign=callsign,
        lines=lines,
        atis_code=str(code).strip().upper() if code else None,
    )


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
