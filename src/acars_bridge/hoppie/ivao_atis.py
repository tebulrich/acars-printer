"""IVAO ATIS from official public Whazzup v2.

There is no dedicated ``_ATIS`` station. Every ATC publishes its own copy:

    clients.atcs[].atis.lines   +  atis.revision

The ATIS-only URL flattens the same fields onto the row. We accept both.
Prefer TWR (airport ATIS), then APP / DEP / GND / DEL. Strip TeamSpeak URIs.
"""

from __future__ import annotations

import re

import httpx

from acars_bridge.hoppie.requests import AtisSide, normalize_icao
from acars_bridge.hoppie.vatsim_atis import VatsimAtis

IVAO_ATIS_URL = "https://api.ivao.aero/v2/tracker/whazzup/atis"
IVAO_TIMEOUT_SECONDS = 10.0

_VOICE_URI = re.compile(r"(?i)ivao\.aero/")
_ROLE_RANK = {
    "ATIS": 0,
    "TWR": 1,
    "APP": 2,
    "DEP": 3,
    "GND": 4,
    "DEL": 5,
}


def parse_ivao_whazzup(payload: object, icao: str) -> list[VatsimAtis]:
    """Accept the ATIS-only array or full Whazzup ``clients.atcs``."""
    return parse_ivao_atis_rows(_atis_rows(payload), icao)


def parse_ivao_atis_rows(rows: list[object], icao: str) -> list[VatsimAtis]:
    """Parse ATC rows; read nested ``atis.lines`` or flattened ``lines``."""
    code = normalize_icao(icao)
    hits: list[VatsimAtis] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        callsign = str(raw.get("callsign") or "").strip().upper()
        if not _airport_station(callsign, code):
            continue
        block = _station_atis(raw)
        lines = _clean_lines(block.get("lines"))
        if not lines:
            continue
        revision = str(block.get("revision") or "").strip().upper() or None
        hits.append(VatsimAtis(callsign=callsign, lines=lines, atis_code=revision))
    hits.sort(key=lambda row: _role_rank(row.callsign))
    return hits


def fetch_ivao_atis(
    icao: str,
    *,
    side: AtisSide | str | None = None,
    client: httpx.Client | None = None,
) -> VatsimAtis | None:
    """Best IVAO ATIS for an airport (TWR first — that is their combined)."""
    del side  # IVAO does not publish split D/A ATIS stations.
    matches = list_ivao_atis(icao, client=client)
    return matches[0] if matches else None


def list_ivao_atis(
    icao: str,
    *,
    client: httpx.Client | None = None,
) -> list[VatsimAtis]:
    owns_client = client is None
    http = client or httpx.Client(timeout=IVAO_TIMEOUT_SECONDS)
    try:
        response = http.get(IVAO_ATIS_URL)
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns_client:
            http.close()
    return parse_ivao_whazzup(payload, icao)


def _atis_rows(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    clients = payload.get("clients")
    if isinstance(clients, dict):
        atcs = clients.get("atcs")
        if isinstance(atcs, list):
            return atcs
    atis = payload.get("atis")
    if isinstance(atis, list):
        return atis
    return []


def _station_atis(raw: dict[str, object]) -> dict[str, object]:
    nested = raw.get("atis")
    if isinstance(nested, dict):
        return nested
    if isinstance(nested, list):
        return {"lines": nested, "revision": raw.get("revision")}
    return raw


def _airport_station(callsign: str, icao: str) -> bool:
    if not callsign.startswith(icao):
        return False
    rest = callsign[len(icao) :]
    return rest == "" or rest.startswith("_")


def _role_rank(callsign: str) -> int:
    role = callsign.rsplit("_", 1)[-1]
    if role == "CTR":
        return 40
    return _ROLE_RANK.get(role, 20)


def _clean_lines(raw: object) -> list[str]:
    parts: list[str] = []
    if isinstance(raw, list):
        parts = [str(item) for item in raw]
    elif isinstance(raw, str) and raw.strip():
        parts = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    for part in parts:
        line = part.strip()
        if not line:
            continue
        if _VOICE_URI.search(line) and len(line.split()) == 1:
            continue
        if line.upper().startswith("CPDLC ID") and len(line) < 28:
            continue
        out.append(line)
    return out
