"""Resolve Hoppie “from” callsign for phone companion / station mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from acars_bridge.services.session import AppSession

StationCallsignSource = Literal["network", "simbrief", "message", "remembered"]


@dataclass(frozen=True, slots=True)
class StationIdentity:
    callsign: str | None
    source: StationCallsignSource | None = None


def resolve_station_identity(session: AppSession) -> StationIdentity:
    """Pick the callsign this PC should use as Hoppie ``from``.

    Priority:
    1. Network callsign filter (explicit override)
    2. Current SimBrief OFP callsign
    3. Most recent inbox message callsign
    4. Last remembered ``station_callsign`` setting

    Empty Network callsign keeps “print all flights”; auto identity is only for
    phone/station outbound. Non-override wins are persisted to ``station_callsign``.
    """
    settings = session.settings
    network = (settings.callsign() or "").strip().upper() or None
    if network:
        return StationIdentity(callsign=network, source="network")

    plan = None
    watcher = session.simbrief_watcher
    if watcher is not None and watcher.state.plan is not None:
        plan = watcher.state.plan
    sb = ""
    if plan is not None:
        sb = (plan.callsign or "").strip().upper()
        if sb and sb != "N/A":
            settings.set_station_callsign(sb)
            return StationIdentity(callsign=sb, source="simbrief")

    recent = session.messages.list_recent(1)
    if recent:
        msg_cs = (recent[0].callsign or "").strip().upper()
        if msg_cs and msg_cs not in {"UNKNOWN", "N/A", "WX", "OFP", "TEST"}:
            settings.set_station_callsign(msg_cs)
            return StationIdentity(callsign=msg_cs, source="message")

    remembered = settings.station_callsign()
    if remembered:
        return StationIdentity(callsign=remembered, source="remembered")

    return StationIdentity(callsign=None, source=None)
