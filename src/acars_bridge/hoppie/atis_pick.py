"""Pick which ATIS station to use — no user dep/arr toggle."""

from __future__ import annotations

from acars_bridge.hoppie.requests import AtisSide
from acars_bridge.hoppie.vatsim_atis import VatsimAtis
from acars_bridge.simconnect.monitor import SimSnapshot, snapshot_in_world


def atis_side_from_snapshot(snapshot: SimSnapshot | None) -> AtisSide | None:
    """DEP on the ground, ARR in the air. None when not in a flight (combined)."""
    if snapshot is None or not snapshot_in_world(snapshot):
        return None
    if snapshot.on_ground:
        return AtisSide.DEP
    return AtisSide.ARR


def is_combined_callsign(callsign: str, icao: str) -> bool:
    """VATSIM combined station is ``ICAO_ATIS`` — not ``_D_ATIS`` / ``_A_ATIS``."""
    cs = callsign.strip().upper()
    code = icao.strip().upper()
    return cs == f"{code}_ATIS"


def split_callsign(icao: str, side: AtisSide | str) -> str:
    letter = "A" if AtisSide(str(side).strip().lower()) is AtisSide.ARR else "D"
    return f"{icao.strip().upper()}_{letter}_ATIS"


def pick_network_atis(
    matches: list[VatsimAtis],
    *,
    icao: str,
    side: AtisSide | str | None,
) -> VatsimAtis | None:
    """Combined if online; else dep/arr from phase; else any published text."""
    if not matches:
        return None
    code = icao.strip().upper()
    with_text = [row for row in matches if row.has_text]
    pool = with_text or list(matches)

    combined = [row for row in pool if is_combined_callsign(row.callsign, code)]
    if combined:
        return combined[0]

    if side is not None:
        wanted = split_callsign(code, side)
        for row in pool:
            if row.callsign == wanted:
                return row

    leftover_combined = [row for row in pool if is_combined_callsign(row.callsign, code)]
    if leftover_combined:
        return leftover_combined[0]
    return pool[0]
