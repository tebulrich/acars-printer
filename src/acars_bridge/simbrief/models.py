from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


def _as_dict(node: Any) -> dict[str, Any] | None:
    if isinstance(node, dict):
        return node
    if isinstance(node, list) and node:
        first = node[0]
        return first if isinstance(first, dict) else None
    return None


def _prop(root: dict[str, Any], *path: str, default: str = "N/A") -> str:
    current: Any = root
    for part in path:
        if isinstance(current, list):
            if not current:
                return default
            current = current[0]
        mapping = _as_dict(current) if not isinstance(current, dict) else current
        if mapping is None or part not in mapping:
            return default
        current = mapping[part]
    if current is None:
        return default
    if isinstance(current, (dict, list)):
        return default
    text = str(current).strip()
    return text if text else default


def _first_prop(root: dict[str, Any], *paths: tuple[str, ...], default: str = "N/A") -> str:
    for path in paths:
        value = _prop(root, *path, default="N/A")
        if value != "N/A":
            return value
    return default


def _format_altitude(feet_str: str) -> str:
    try:
        feet = int(float(feet_str))
    except (TypeError, ValueError):
        return "N/A"
    if feet <= 0:
        return "N/A"
    if feet >= 18000:
        return f"FL{feet // 100}"
    return f"{feet} ft"


def _format_duration_seconds(seconds_str: str) -> str:
    try:
        seconds = int(float(seconds_str))
    except (TypeError, ValueError):
        return "N/A"
    if seconds <= 0:
        return "N/A"
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    return f"{hours}h {minutes:02d}m"


def _format_epoch_date(epoch_str: str) -> str:
    """Format SimBrief epoch as ``01JAN30`` (Zulu calendar date)."""
    try:
        epoch = int(float(epoch_str))
    except (TypeError, ValueError):
        return "N/A"
    if epoch <= 0:
        return "N/A"
    dt = datetime.fromtimestamp(epoch, tz=UTC)
    return dt.strftime("%d%b%y").upper()


def _format_epoch_time(epoch_str: str) -> str:
    """Format SimBrief epoch as ``00:00Z``."""
    try:
        epoch = int(float(epoch_str))
    except (TypeError, ValueError):
        return "N/A"
    if epoch <= 0:
        return "N/A"
    dt = datetime.fromtimestamp(epoch, tz=UTC)
    return dt.strftime("%H:%MZ")


def _format_epoch_zulu(epoch_str: str) -> str:
    """Format SimBrief epoch as ``01JAN30 00:00Z`` (date + Zulu time)."""
    date = _format_epoch_date(epoch_str)
    time = _format_epoch_time(epoch_str)
    if date == "N/A" or time == "N/A":
        return "N/A"
    return f"{date} {time}"


def _parse_epoch(epoch_str: str) -> datetime | None:
    try:
        epoch = int(float(epoch_str))
    except (TypeError, ValueError):
        return None
    if epoch <= 0:
        return None
    return datetime.fromtimestamp(epoch, tz=UTC)


@dataclass(frozen=True, slots=True)
class SimBriefFlightPlan:
    ofp_id: str
    callsign: str
    airline_icao: str
    flight_number: str
    aircraft_icao: str
    aircraft_name: str
    aircraft_reg: str
    origin_icao: str
    origin_iata: str
    origin_name: str
    dest_icao: str
    dest_iata: str
    dest_name: str
    alternate_icao: str
    alternate_name: str
    route: str
    cruise_altitude: str
    distance_nm: str
    flight_time_formatted: str
    units: str
    block_fuel: str
    taxi_fuel: str
    takeoff_fuel: str
    zfw: str
    tow: str
    max_zfw: str
    max_tow: str
    pax_count: str
    pax_weight_avg: str
    cargo_weight: str
    sched_out_zulu: str
    sched_in_zulu: str
    sched_out_utc: datetime | None
    sched_in_utc: datetime | None = None
    flight_date_zulu: str = "N/A"
    # Optional OFP extras for takeoff / weights card (real SimBrief fields).
    origin_runway: str = "N/A"
    dest_runway: str = "N/A"
    cost_index: str = "N/A"
    trip_fuel: str = "N/A"
    contingency_fuel: str = "N/A"
    alternate_fuel: str = "N/A"
    reserve_fuel: str = "N/A"
    landing_fuel: str = "N/A"
    est_ldw: str = "N/A"
    avg_wind_comp: str = "N/A"
    avg_temp_dev: str = "N/A"

    @classmethod
    def from_json(cls, root: dict[str, Any]) -> SimBriefFlightPlan:
        airline = _prop(root, "general", "icao_airline")
        flight_number = _prop(root, "general", "flight_number")
        atc = _prop(root, "atc", "callsign")
        callsign = atc if atc != "N/A" else f"{airline}{flight_number}"

        sched_out_raw = _prop(root, "times", "sched_out")
        sched_in_raw = _prop(root, "times", "sched_in")
        sched_out_utc = _parse_epoch(sched_out_raw)
        sched_in_utc = _parse_epoch(sched_in_raw)

        ofp_id = _prop(root, "params", "request_id", default="")
        if not ofp_id or ofp_id == "N/A":
            ofp_id = _prop(root, "params", "static_id", default="")
        if not ofp_id or ofp_id == "N/A":
            # Stable fallback when SimBrief omits request_id.
            ofp_id = "|".join(
                [
                    callsign,
                    _prop(root, "origin", "icao_code"),
                    _prop(root, "destination", "icao_code"),
                    sched_out_raw if sched_out_raw != "N/A" else "",
                    _prop(root, "general", "route"),
                ]
            )

        return cls(
            ofp_id=ofp_id,
            callsign=callsign,
            airline_icao=airline,
            flight_number=flight_number,
            aircraft_icao=_prop(root, "aircraft", "icaocode"),
            aircraft_name=_prop(root, "aircraft", "name"),
            aircraft_reg=_prop(root, "aircraft", "reg"),
            origin_icao=_prop(root, "origin", "icao_code"),
            origin_iata=_prop(root, "origin", "iata_code"),
            origin_name=_prop(root, "origin", "name"),
            dest_icao=_prop(root, "destination", "icao_code"),
            dest_iata=_prop(root, "destination", "iata_code"),
            dest_name=_prop(root, "destination", "name"),
            alternate_icao=_prop(root, "alternate", "icao_code"),
            alternate_name=_prop(root, "alternate", "name"),
            route=_prop(root, "general", "route"),
            cruise_altitude=_format_altitude(_prop(root, "general", "initial_altitude")),
            distance_nm=_prop(root, "general", "route_distance"),
            flight_time_formatted=_format_duration_seconds(
                _prop(root, "times", "est_time_enroute")
            ),
            units=_prop(root, "params", "units", default="kg"),
            block_fuel=_prop(root, "fuel", "plan_ramp"),
            taxi_fuel=_prop(root, "fuel", "taxi"),
            takeoff_fuel=_prop(root, "fuel", "plan_takeoff"),
            zfw=_prop(root, "weights", "est_zfw"),
            tow=_prop(root, "weights", "est_tow"),
            max_zfw=_prop(root, "weights", "max_zfw"),
            max_tow=_prop(root, "weights", "max_tow"),
            pax_count=_prop(root, "weights", "pax_count_actual"),
            pax_weight_avg=_prop(root, "weights", "pax_weight"),
            cargo_weight=_prop(root, "weights", "cargo"),
            sched_out_zulu=_format_epoch_zulu(sched_out_raw),
            sched_in_zulu=_format_epoch_zulu(sched_in_raw),
            sched_out_utc=sched_out_utc,
            sched_in_utc=sched_in_utc,
            flight_date_zulu=_format_epoch_date(sched_out_raw),
            origin_runway=_prop(root, "origin", "plan_rwy"),
            dest_runway=_prop(root, "destination", "plan_rwy"),
            cost_index=_prop(root, "general", "costindex"),
            trip_fuel=_first_prop(
                root,
                ("fuel", "enroute_burn"),
                ("fuel", "plan_enroute"),
            ),
            contingency_fuel=_prop(root, "fuel", "contingency"),
            alternate_fuel=_prop(root, "fuel", "alternate"),
            reserve_fuel=_prop(root, "fuel", "reserve"),
            landing_fuel=_prop(root, "fuel", "plan_landing"),
            est_ldw=_prop(root, "weights", "est_ldw"),
            avg_wind_comp=_prop(root, "general", "avg_wind_comp"),
            avg_temp_dev=_prop(root, "general", "avg_temp_dev"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ofp_id": self.ofp_id,
            "callsign": self.callsign,
            "airline_icao": self.airline_icao,
            "flight_number": self.flight_number,
            "aircraft_icao": self.aircraft_icao,
            "aircraft_name": self.aircraft_name,
            "aircraft_reg": self.aircraft_reg,
            "origin_icao": self.origin_icao,
            "origin_iata": self.origin_iata,
            "origin_name": self.origin_name,
            "dest_icao": self.dest_icao,
            "dest_iata": self.dest_iata,
            "dest_name": self.dest_name,
            "alternate_icao": self.alternate_icao,
            "alternate_name": self.alternate_name,
            "route": self.route,
            "cruise_altitude": self.cruise_altitude,
            "distance_nm": self.distance_nm,
            "flight_time_formatted": self.flight_time_formatted,
            "units": self.units,
            "block_fuel": self.block_fuel,
            "taxi_fuel": self.taxi_fuel,
            "takeoff_fuel": self.takeoff_fuel,
            "zfw": self.zfw,
            "tow": self.tow,
            "max_zfw": self.max_zfw,
            "max_tow": self.max_tow,
            "pax_count": self.pax_count,
            "pax_weight_avg": self.pax_weight_avg,
            "cargo_weight": self.cargo_weight,
            "sched_out_zulu": self.sched_out_zulu,
            "sched_in_zulu": self.sched_in_zulu,
            "sched_out_utc": self.sched_out_utc.isoformat() if self.sched_out_utc else None,
            "sched_in_utc": self.sched_in_utc.isoformat() if self.sched_in_utc else None,
            "flight_date_zulu": self.flight_date_zulu,
            "origin_runway": self.origin_runway,
            "dest_runway": self.dest_runway,
            "cost_index": self.cost_index,
            "trip_fuel": self.trip_fuel,
            "contingency_fuel": self.contingency_fuel,
            "alternate_fuel": self.alternate_fuel,
            "reserve_fuel": self.reserve_fuel,
            "landing_fuel": self.landing_fuel,
            "est_ldw": self.est_ldw,
            "avg_wind_comp": self.avg_wind_comp,
            "avg_temp_dev": self.avg_temp_dev,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SimBriefFlightPlan:
        def _parse_iso(raw: object) -> datetime | None:
            if not isinstance(raw, str) or not raw:
                return None
            try:
                dt = datetime.fromisoformat(raw)
            except ValueError:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt

        sched_out = _parse_iso(data.get("sched_out_utc"))
        sched_in = _parse_iso(data.get("sched_in_utc"))
        flight_date = str(data.get("flight_date_zulu") or "N/A")
        if flight_date == "N/A" and sched_out is not None:
            flight_date = sched_out.strftime("%d%b%y").upper()
        sched_out_zulu = str(data.get("sched_out_zulu") or "N/A")
        sched_in_zulu = str(data.get("sched_in_zulu") or "N/A")
        # Refresh display strings from datetimes so older locks pick up date.
        if sched_out is not None:
            sched_out_zulu = sched_out.strftime("%d%b%y %H:%M").upper() + "Z"
            flight_date = sched_out.strftime("%d%b%y").upper()
        if sched_in is not None:
            sched_in_zulu = sched_in.strftime("%d%b%y %H:%M").upper() + "Z"

        return cls(
            ofp_id=str(data.get("ofp_id") or ""),
            callsign=str(data.get("callsign") or "N/A"),
            airline_icao=str(data.get("airline_icao") or "N/A"),
            flight_number=str(data.get("flight_number") or "N/A"),
            aircraft_icao=str(data.get("aircraft_icao") or "N/A"),
            aircraft_name=str(data.get("aircraft_name") or "N/A"),
            aircraft_reg=str(data.get("aircraft_reg") or "N/A"),
            origin_icao=str(data.get("origin_icao") or "N/A"),
            origin_iata=str(data.get("origin_iata") or "N/A"),
            origin_name=str(data.get("origin_name") or "N/A"),
            dest_icao=str(data.get("dest_icao") or "N/A"),
            dest_iata=str(data.get("dest_iata") or "N/A"),
            dest_name=str(data.get("dest_name") or "N/A"),
            alternate_icao=str(data.get("alternate_icao") or "N/A"),
            alternate_name=str(data.get("alternate_name") or "N/A"),
            route=str(data.get("route") or "N/A"),
            cruise_altitude=str(data.get("cruise_altitude") or "N/A"),
            distance_nm=str(data.get("distance_nm") or "N/A"),
            flight_time_formatted=str(data.get("flight_time_formatted") or "N/A"),
            units=str(data.get("units") or "kg"),
            block_fuel=str(data.get("block_fuel") or "N/A"),
            taxi_fuel=str(data.get("taxi_fuel") or "N/A"),
            takeoff_fuel=str(data.get("takeoff_fuel") or "N/A"),
            zfw=str(data.get("zfw") or "N/A"),
            tow=str(data.get("tow") or "N/A"),
            max_zfw=str(data.get("max_zfw") or "N/A"),
            max_tow=str(data.get("max_tow") or "N/A"),
            pax_count=str(data.get("pax_count") or "N/A"),
            pax_weight_avg=str(data.get("pax_weight_avg") or "N/A"),
            cargo_weight=str(data.get("cargo_weight") or "N/A"),
            sched_out_zulu=sched_out_zulu,
            sched_in_zulu=sched_in_zulu,
            sched_out_utc=sched_out,
            sched_in_utc=sched_in,
            flight_date_zulu=flight_date,
            origin_runway=str(data.get("origin_runway") or "N/A"),
            dest_runway=str(data.get("dest_runway") or "N/A"),
            cost_index=str(data.get("cost_index") or "N/A"),
            trip_fuel=str(data.get("trip_fuel") or "N/A"),
            contingency_fuel=str(data.get("contingency_fuel") or "N/A"),
            alternate_fuel=str(data.get("alternate_fuel") or "N/A"),
            reserve_fuel=str(data.get("reserve_fuel") or "N/A"),
            landing_fuel=str(data.get("landing_fuel") or "N/A"),
            est_ldw=str(data.get("est_ldw") or "N/A"),
            avg_wind_comp=str(data.get("avg_wind_comp") or "N/A"),
            avg_temp_dev=str(data.get("avg_temp_dev") or "N/A"),
        )

    def placeholder_map(self) -> dict[str, str]:
        return {
            "Callsign": self.callsign,
            "AirlineIcao": self.airline_icao,
            "FlightNumber": self.flight_number,
            "AircraftIcao": self.aircraft_icao,
            "AircraftName": self.aircraft_name,
            "AircraftReg": self.aircraft_reg,
            "OriginIcao": self.origin_icao,
            "OriginIata": self.origin_iata,
            "OriginName": self.origin_name,
            "DestIcao": self.dest_icao,
            "DestIata": self.dest_iata,
            "DestName": self.dest_name,
            "AlternateIcao": self.alternate_icao,
            "AlternateName": self.alternate_name,
            "Route": self.route,
            "CruiseAltitude": self.cruise_altitude,
            "DistanceNm": self.distance_nm,
            "FlightTimeFormatted": self.flight_time_formatted,
            "SchedOutZulu": (
                self.sched_out_utc.strftime("%d%b%y %H:%M").upper() + "Z"
                if self.sched_out_utc is not None
                else self.sched_out_zulu
            ),
            "SchedInZulu": (
                self.sched_in_utc.strftime("%d%b%y %H:%M").upper() + "Z"
                if self.sched_in_utc is not None
                else self.sched_in_zulu
            ),
            "FlightDate": (
                self.sched_out_utc.strftime("%d%b%y").upper()
                if self.sched_out_utc is not None
                else self.flight_date_zulu
            ),
            "Units": self.units,
            "BlockFuel": self.block_fuel,
            "TaxiFuel": self.taxi_fuel,
            "TakeoffFuel": self.takeoff_fuel,
            "Zfw": self.zfw,
            "Tow": self.tow,
            "MaxZfw": self.max_zfw,
            "MaxTow": self.max_tow,
            "PaxCount": self.pax_count,
            "PaxWeightAvg": self.pax_weight_avg,
            "CargoWeight": self.cargo_weight,
            "OriginRunway": self.origin_runway,
            "DestRunway": self.dest_runway,
            "CostIndex": self.cost_index,
            "TripFuel": self.trip_fuel,
            "ContingencyFuel": self.contingency_fuel,
            "AlternateFuel": self.alternate_fuel,
            "ReserveFuel": self.reserve_fuel,
            "LandingFuel": self.landing_fuel,
            "EstLdw": self.est_ldw,
            "AvgWindComp": self.avg_wind_comp,
            "AvgTempDev": self.avg_temp_dev,
        }


def is_eligible_for_autoprint(
    plan: SimBriefFlightPlan,
    *,
    now: datetime,
    last_ofp_id: str | None,
    late_grace: timedelta = timedelta(minutes=60),
) -> bool:
    """True when OFP is new and SOBT is still usable (future or within late grace)."""
    if last_ofp_id and plan.ofp_id == last_ofp_id:
        return False
    if plan.sched_out_utc is None:
        return False
    return plan.sched_out_utc >= (now - late_grace)
