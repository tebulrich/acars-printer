"""Guard companion station mode against callsign conflicts (hook/tap vs station)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from acars_bridge.hoppie.errors import CallsignInUseError, HoppieError

if TYPE_CHECKING:
    from acars_bridge.services.session import AppSession


@dataclass(frozen=True, slots=True)
class StationProbeResult:
    ok: bool
    reason: str | None = None
    conflict: bool = False


def probe_station_callsign(session: AppSession) -> StationProbeResult:
    """Ask Hoppie whether this PC may own the callsign via ``poll``.

    If the aircraft (or any other client) already holds the callsign, Hoppie
    returns ``error callsign already in use`` — that is the hard signal that
    station mode would fight hook/tap mode.
    """
    from acars_bridge.services.station_identity import resolve_station_identity

    settings = session.settings
    logon = settings.hoppie_logon()
    identity = resolve_station_identity(session)
    callsign = identity.callsign
    if not logon:
        return StationProbeResult(
            ok=False,
            reason="Set a Hoppie logon code before enabling station mode.",
        )
    if not callsign:
        return StationProbeResult(
            ok=False,
            reason=(
                "No callsign yet — load a SimBrief OFP, print/tap one ACARS "
                "message, or set the Network callsign filter."
            ),
        )
    try:
        session.station.fetch(logon, callsign)
    except CallsignInUseError as exc:
        return StationProbeResult(
            ok=False,
            conflict=True,
            reason=(
                f"Callsign {callsign} is already in use on Hoppie "
                f"(usually the aircraft in Connect/tap mode). "
                f"Leave station mode off and keep using the plane’s ACARS. "
                f"({exc})"
            ),
        )
    except HoppieError as exc:
        return StationProbeResult(ok=False, reason=str(exc))
    except Exception as exc:  # noqa: BLE001
        return StationProbeResult(ok=False, reason=f"Hoppie probe failed: {exc}")
    return StationProbeResult(ok=True)
