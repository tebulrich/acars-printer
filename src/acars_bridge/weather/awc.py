from __future__ import annotations

import logging

import httpx

from acars_bridge.hoppie.requests import normalize_icao

log = logging.getLogger(__name__)

AWC_BASE = "https://aviationweather.gov/api/data"
AWC_TIMEOUT_SECONDS = 12.0


def fetch_metar_raw(
    icao: str,
    *,
    client: httpx.Client | None = None,
) -> str | None:
    """Latest METAR raw observation text from AWC, or None."""
    code = normalize_icao(icao)
    rows = _get_json(f"{AWC_BASE}/metar", {"ids": code, "format": "json"}, client=client)
    if not rows:
        return None
    raw = rows[0].get("rawOb") if isinstance(rows[0], dict) else None
    text = str(raw).strip() if raw else ""
    return text or None


def fetch_taf_raw(
    icao: str,
    *,
    client: httpx.Client | None = None,
) -> str | None:
    """Latest TAF raw text from AWC, or None."""
    code = normalize_icao(icao)
    rows = _get_json(f"{AWC_BASE}/taf", {"ids": code, "format": "json"}, client=client)
    if not rows:
        return None
    raw = rows[0].get("rawTAF") if isinstance(rows[0], dict) else None
    text = str(raw).strip() if raw else ""
    return text or None


def fetch_airport_coords(
    icao: str,
    *,
    client: httpx.Client | None = None,
) -> tuple[float, float] | None:
    """Airport (lat, lon) degrees from AWC airport API, or METAR station lat/lon."""
    code = normalize_icao(icao)
    rows = _get_json(
        f"{AWC_BASE}/airport", {"ids": code, "format": "json"}, client=client
    )
    coords = _coords_from_rows(rows)
    if coords is not None:
        return coords
    # Some stations appear in METAR but not airport — use observation lat/lon.
    metar_rows = _get_json(
        f"{AWC_BASE}/metar", {"ids": code, "format": "json"}, client=client
    )
    return _coords_from_rows(metar_rows)


def _coords_from_rows(rows: list[dict] | None) -> tuple[float, float] | None:
    if not rows:
        return None
    row = rows[0]
    if not isinstance(row, dict):
        return None
    try:
        lat = float(row["lat"])
        lon = float(row["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    return lat, lon


def _get_json(
    url: str,
    params: dict[str, str],
    *,
    client: httpx.Client | None,
) -> list[dict] | None:
    owns = client is None
    http = client or httpx.Client(timeout=AWC_TIMEOUT_SECONDS)
    try:
        response = http.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    except Exception:
        log.exception("AWC request failed url=%s params=%s", url, params)
        return None
    finally:
        if owns:
            http.close()
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return [data]
    return None
