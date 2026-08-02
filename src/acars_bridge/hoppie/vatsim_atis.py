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

    code = normalize_icao(icao)
    preferred = _preferred_callsigns(code, side, online={m.callsign for m in matches})
    by_cs = {m.callsign: m for m in matches}
    for name in preferred:
        hit = by_cs.get(name)
        if hit is not None and hit.has_text:
            return hit
    for name in preferred:
        hit = by_cs.get(name)
        if hit is not None:
            return hit
    for hit in matches:
        if hit.has_text:
            return hit
    return matches[0]


def hoppie_vatatis_packets(
    icao: str,
    *,
    side: AtisSide | str | None = None,
    online_callsigns: set[str] | None = None,
) -> list[str]:
    """Hoppie ``vatatis`` packets to try, ordered for real VATSIM stations.

    Hoppie matches the live ATC callsign. Many airports (EDDN, EDDS, …) publish
    combined ``ICAO_ATIS``; Hoppie then answers ``vatatis ICAO`` and rejects
    ``ICAO_D_ATIS`` / ``ICAO_ATIS`` with ``THIS ATIS IS NOT AVAILABLE``.

    Split D/A stations are only requested when that callsign is actually online.
    """
    code = normalize_icao(icao)
    online = {cs.upper() for cs in (online_callsigns or set())}
    packets: list[str] = []

    if side is not None:
        side_value = AtisSide(str(side).strip().lower())
        letter = "A" if side_value is AtisSide.ARR else "D"
        specific = f"{code}_{letter}_ATIS"
        if specific in online:
            packets.append(f"{AtisSource.VATSIM.value} {specific}")

    # Plain ICAO is what Hoppie resolves for combined ATIS (verified EDDN/EDDS).
    packets.append(f"{AtisSource.VATSIM.value} {code}")

    # Last resort: explicit combined callsign / opposite side if online.
    if f"{code}_ATIS" in online:
        packets.append(f"{AtisSource.VATSIM.value} {code}_ATIS")
    if side is not None:
        side_value = AtisSide(str(side).strip().lower())
        other = "D" if side_value is AtisSide.ARR else "A"
        other_cs = f"{code}_{other}_ATIS"
        if other_cs in online:
            packets.append(f"{AtisSource.VATSIM.value} {other_cs}")

    return _unique(packets)


def _preferred_callsigns(
    icao: str,
    side: AtisSide | str | None,
    *,
    online: set[str],
) -> list[str]:
    names: list[str] = []
    if side is not None:
        side_value = AtisSide(str(side).strip().lower())
        letter = "A" if side_value is AtisSide.ARR else "D"
        specific = f"{icao}_{letter}_ATIS"
        if specific in online:
            names.append(specific)
    if f"{icao}_ATIS" in online:
        names.append(f"{icao}_ATIS")
    if side is not None:
        side_value = AtisSide(str(side).strip().lower())
        other = "D" if side_value is AtisSide.ARR else "A"
        other_cs = f"{icao}_{other}_ATIS"
        if other_cs in online:
            names.append(other_cs)
    # Keep any other online callsigns (rare variants) at the end.
    for cs in sorted(online):
        if cs not in names:
            names.append(cs)
    return names


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
