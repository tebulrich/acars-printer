from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from acars_bridge.hoppie.requests import AtisSide, normalize_icao
from acars_bridge.hoppie.vatsim_atis import fetch_vatsim_atis
from acars_bridge.weather.awc import fetch_airport_coords, fetch_metar_raw, fetch_taf_raw
from acars_bridge.weather.distance import great_circle_nm

if TYPE_CHECKING:
    from acars_bridge.models.settings import SettingsStore
    from acars_bridge.services.print_manager import PrintManager
    from acars_bridge.services.sterile import SterileGate
    from acars_bridge.simbrief.models import SimBriefFlightPlan
    from acars_bridge.simconnect.monitor import SimSnapshot

log = logging.getLogger(__name__)


def should_trigger_dest_wx(
    distance_to_dest_nm: float,
    distance_to_origin_nm: float,
    threshold_nm: float,
    *,
    on_ground: bool,
) -> bool:
    """Whether geometry + ground state say dest WX may print.

    Within the destination NM ring: suppress while on the ground (covers
    near-origin / short-hop preflight). Once airborne inside the ring, allow —
    including short hops that never leave the ring. Do not require "far from
    origin" permanently. Caller still checks sterile/power and once-per-OFP.
    """
    if distance_to_dest_nm > threshold_nm:
        return False
    if on_ground:
        # Near-origin on ground (and any on-ground) — wait until airborne.
        _ = distance_to_origin_nm
        return False
    return True


class AutoWxService:
    """Print real dest ATIS/METAR/TAF once per OFP when inside the NM ring."""

    def __init__(
        self,
        *,
        settings: SettingsStore,
        print_manager: PrintManager,
        sterile: SterileGate,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self.print_manager = print_manager
        self.sterile = sterile
        self._http = http_client
        self._printed_ofp_ids: set[str] = set()
        self._coord_cache: dict[str, tuple[float, float]] = {}

    def consider(
        self,
        snap: SimSnapshot,
        plan: SimBriefFlightPlan,
    ) -> int:
        """Evaluate snapshot + OFP; print selected WX once. Returns strips printed."""
        if not self.settings.wx_auto_enabled():
            return 0
        kinds = self.settings.wx_auto_kinds()
        if not kinds:
            return 0
        if not snap.connected:
            return 0
        if snap.latitude is None or snap.longitude is None:
            return 0
        ofp_id = (plan.ofp_id or "").strip()
        if not ofp_id or ofp_id in self._printed_ofp_ids:
            return 0

        try:
            dest = normalize_icao(plan.dest_icao)
            origin = normalize_icao(plan.origin_icao)
        except ValueError:
            return 0

        dest_coords = self._airport_coords(dest)
        origin_coords = self._airport_coords(origin)
        if dest_coords is None or origin_coords is None:
            return 0

        dist_dest = great_circle_nm(
            snap.latitude, snap.longitude, dest_coords[0], dest_coords[1]
        )
        dist_origin = great_circle_nm(
            snap.latitude, snap.longitude, origin_coords[0], origin_coords[1]
        )
        threshold = float(self.settings.wx_auto_nm())
        if not should_trigger_dest_wx(
            dist_dest,
            dist_origin,
            threshold,
            on_ground=snap.on_ground,
        ):
            return 0

        # Wait for sterile/power clear while still airborne — do not defer to a
        # flush that might run on the ground after landing.
        if self.sterile.is_blocking:
            return 0

        bodies = self._fetch_bodies(dest, kinds)
        if not bodies:
            return 0

        printed = self._print_bodies(plan, bodies)
        if printed > 0:
            self._printed_ofp_ids.add(ofp_id)
            log.info(
                "auto dest WX printed ofp=%s dest=%s kinds=%s dist_nm=%.1f",
                ofp_id,
                dest,
                sorted(kinds),
                dist_dest,
            )
        return printed

    def _airport_coords(self, icao: str) -> tuple[float, float] | None:
        cached = self._coord_cache.get(icao)
        if cached is not None:
            return cached
        coords = fetch_airport_coords(icao, client=self._http)
        if coords is not None:
            self._coord_cache[icao] = coords
        return coords

    def _fetch_bodies(self, dest: str, kinds: set[str]) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        if "atis" in kinds:
            try:
                atis = fetch_vatsim_atis(dest, side=AtisSide.ARR, client=self._http)
            except Exception:
                log.exception("VATSIM ATIS fetch failed dest=%s", dest)
                atis = None
            if atis is not None:
                out.append(("auto_atis", atis.body()))
        if "metar" in kinds:
            metar = fetch_metar_raw(dest, client=self._http)
            if metar:
                out.append(("auto_metar", metar))
        if "taf" in kinds:
            taf = fetch_taf_raw(dest, client=self._http)
            if taf:
                out.append(("auto_taf", taf))
        return out

    def _print_bodies(
        self,
        plan: SimBriefFlightPlan,
        bodies: list[tuple[str, str]],
    ) -> int:
        settings = self.settings.as_printer_settings()
        callsign = plan.callsign if plan.callsign and plan.callsign != "N/A" else "WX"
        count = 0
        for ticket_type, body in bodies:
            self.print_manager.print_ticket(
                body,
                settings,
                callsign=callsign,
                ticket_type=ticket_type,
                sender="AUTO-WX",
            )
            count += 1
        return count
