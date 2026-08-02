from __future__ import annotations

from enum import StrEnum


class WeatherKind(StrEnum):
    METAR = "metar"
    TAF = "taf"
    SHORTTAF = "shorttaf"


class AtisSource(StrEnum):
    VATSIM = "vatatis"
    IVAO = "ivaoatis"
    PILOTEDGE = "peatis"


class AtisSide(StrEnum):
    ARR = "arr"
    DEP = "dep"


def normalize_icao(icao: str) -> str:
    value = icao.strip().upper()
    if len(value) != 4 or not value.isalpha():
        raise ValueError("ICAO must be 4 letters (e.g. EGLL).")
    return value


def build_weather_packet(kind: WeatherKind | str, icao: str) -> str:
    kind_value = WeatherKind(str(kind).strip().lower())
    return f"{kind_value.value} {normalize_icao(icao)}"


def build_atis_packet(
    icao: str,
    *,
    source: AtisSource | str = AtisSource.VATSIM,
    side: AtisSide | str | None = None,
) -> str:
    """Build Hoppie inforeq ATIS packet.

    VATSIM D-ATIS often splits arrival/departure as ``ICAO_A_ATIS`` / ``ICAO_D_ATIS``.
    Plain ``vatatis ICAO`` is used when ``side`` is omitted (fallback / single ATIS).
    """
    source_value = AtisSource(str(source).strip().lower())
    code = normalize_icao(icao)
    if side is None or source_value is not AtisSource.VATSIM:
        return f"{source_value.value} {code}"
    side_value = AtisSide(str(side).strip().lower())
    suffix = "A_ATIS" if side_value is AtisSide.ARR else "D_ATIS"
    return f"{source_value.value} {code}_{suffix}"


def build_pdc_telex(
    *,
    callsign: str,
    aircraft_type: str,
    destination: str,
    departure: str,
    stand: str,
    atis_letter: str,
) -> str:
    cs = callsign.strip().upper()
    ac = aircraft_type.strip().upper()
    dest = normalize_icao(destination)
    dep = normalize_icao(departure)
    gate = stand.strip().upper()
    letter = atis_letter.strip().upper()
    if not cs:
        raise ValueError("Callsign is required.")
    if not ac:
        raise ValueError("Aircraft type is required.")
    if not gate:
        raise ValueError("Stand / gate is required.")
    if len(letter) != 1 or not letter.isalpha():
        raise ValueError("ATIS letter must be a single letter (e.g. D).")
    return (
        "REQUEST PREDEP CLEARANCE\n"
        f"{cs} {ac} TO {dest}\n"
        f"AT {dep} STAND {gate}\n"
        f"ATIS {letter}"
    )


def build_position_packet(
    *,
    latitude: str,
    longitude: str,
    altitude: str,
    time_utc: str,
    next_waypoint: str | None = None,
    eta: str | None = None,
    remark: str | None = None,
) -> str:
    lat = latitude.strip().upper()
    lon = longitude.strip().upper()
    alt = altitude.strip().upper()
    when = time_utc.strip().upper()
    if not lat or not lon:
        raise ValueError("Latitude and longitude are required.")
    if not alt:
        raise ValueError("Altitude / flight level is required.")
    if not when:
        raise ValueError("UTC time is required (e.g. 1435Z).")
    lines = [
        f"LAT {lat}",
        f"LON {lon}",
        f"ALT {alt}",
        f"TIME {when}",
    ]
    if next_waypoint and next_waypoint.strip():
        lines.append(f"NEXT {next_waypoint.strip().upper()}")
    if eta and eta.strip():
        lines.append(f"ETA {eta.strip().upper()}")
    if remark and remark.strip():
        lines.append(f"RMK {remark.strip()}")
    return "\n".join(lines)
