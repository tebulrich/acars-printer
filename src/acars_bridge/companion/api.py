"""JSON API handlers for the phone companion."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from acars_bridge.companion.lan import lan_ipv4_addresses, primary_lan_ip
from acars_bridge.hoppie.errors import HoppieError, SendNotAllowedError
from acars_bridge.hoppie.requests import AtisSide, AtisSource, WeatherKind

if TYPE_CHECKING:
    from acars_bridge.bridge.runtime import BridgeRuntime
    from acars_bridge.models.messages import StoredMessage
    from acars_bridge.services.companion_station import CompanionStationPoller


def _message_dict(msg: StoredMessage, *, body: bool = True) -> dict[str, Any]:
    station = msg.sender if msg.direction == "in" else (msg.to_station or msg.recipient)
    row: dict[str, Any] = {
        "id": msg.id,
        "received_at": msg.received_at,
        "direction": msg.direction,
        "callsign": msg.callsign,
        "station": station or "",
        "message_type": msg.message_type,
        "preview": (msg.normalized_body or "").replace("\n", " ")[:80],
    }
    if body:
        row["normalized_body"] = msg.normalized_body
        row["raw_payload"] = msg.raw_payload
        row["sender"] = msg.sender
        row["recipient"] = msg.recipient
        row["to_station"] = msg.to_station
    return row


class CompanionApi:
    def __init__(
        self,
        runtime: BridgeRuntime,
        *,
        poller: CompanionStationPoller | None = None,
    ) -> None:
        self.runtime = runtime
        self.poller = poller

    @property
    def session(self):
        return self.runtime.session

    def status(self) -> dict[str, Any]:
        from acars_bridge.services.station_identity import resolve_station_identity

        s = self.session.settings
        port = s.companion_port()
        token = s.companion_token()
        ip = primary_lan_ip()
        poller_err = self.poller.last_error if self.poller else None
        identity = resolve_station_identity(self.session)
        wire = self.session.wire_session.status_dict()
        station_on = s.companion_station_enabled()
        wire_ready = bool(wire.get("ready"))
        can_send = station_on or wire_ready
        # Prefer wire “from” for display when sending via Connect.
        display_cs = (
            str(wire.get("from") or "")
            if wire_ready and not station_on
            else (identity.callsign or "")
        )
        return {
            "product": "ACARS Print Bridge",
            "callsign": display_cs or identity.callsign or "",
            "callsign_source": (
                "wire"
                if wire_ready and not station_on
                else (identity.source or "")
            ),
            "callsign_filter": s.callsign() or "",
            "companion_enabled": s.companion_enabled(),
            "companion_station_enabled": station_on,
            "companion_port": port,
            "station_polling": bool(self.poller and self.poller.running),
            "station_error": poller_err,
            "message_count": self.session.messages.count(),
            "lan_ips": lan_ipv4_addresses(),
            "url": f"http://{ip}:{port}/?token={token}",
            "has_logon": bool(s.hoppie_logon()) or wire_ready,
            "has_callsign": bool(display_cs or identity.callsign),
            "wire_session": wire,
            "can_send": can_send,
            "pdc_defaults": {
                "station": s.get("req_pdc_station") or "",
                "departure": s.get("req_pdc_dep") or "",
                "destination": s.get("req_pdc_dest") or "",
                "aircraft_type": s.get("req_pdc_actype") or "",
                "stand": s.get("req_pdc_stand") or "",
                "atis_letter": s.get("req_pdc_atis") or "",
            },
            "last_icao": s.get("req_last_icao") or "",
        }

    def messages(
        self,
        *,
        since_id: int = 0,
        before_id: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        if since_id > 0:
            rows = self.session.messages.list_since(since_id, limit=limit)
            # newest-last for append; UI may reverse
            items = [_message_dict(m) for m in rows]
        else:
            rows = self.session.messages.list_page(before_id=before_id, limit=limit)
            items = [_message_dict(m) for m in rows]
        return {
            "messages": items,
            "count": self.session.messages.count(),
        }

    def message(self, message_id: int) -> dict[str, Any]:
        msg = self.session.messages.get(message_id)
        if msg is None:
            raise KeyError(f"Message {message_id} not found")
        return _message_dict(msg, body=True)

    def send_telex(self, to: str, text: str) -> dict[str, Any]:
        stored = self.session.outbound.send_telex(to, text)
        self.runtime.emit_event("new_messages", {"count": 1})
        return {"ok": True, "message": _message_dict(stored)}

    def request_weather(self, kind: str, icao: str) -> dict[str, Any]:
        rows = self.session.outbound.request_weather(WeatherKind(kind), icao)
        self.runtime.emit_event("new_messages", {"count": len(rows)})
        return {
            "ok": True,
            "messages": [_message_dict(m) for m in rows],
            "print_stats": dict(self.session.outbound.last_print_stats),
        }

    def request_atis(
        self,
        icao: str,
        *,
        side: str | None = "dep",
        source: str = "vatatis",
    ) -> dict[str, Any]:
        side_val: AtisSide | str | None
        if side in (None, "", "none", "plain"):
            side_val = None
        else:
            side_val = AtisSide(str(side).strip().lower())
        rows = self.session.outbound.request_atis(
            icao,
            source=AtisSource(source),
            side=side_val,
        )
        self.runtime.emit_event("new_messages", {"count": len(rows)})
        return {
            "ok": True,
            "messages": [_message_dict(m) for m in rows],
            "print_stats": dict(self.session.outbound.last_print_stats),
        }

    def request_pdc(self, body: dict[str, Any]) -> dict[str, Any]:
        stored = self.session.outbound.request_pdc(
            station=str(body.get("station") or ""),
            departure=str(body.get("departure") or ""),
            destination=str(body.get("destination") or ""),
            aircraft_type=str(body.get("aircraft_type") or ""),
            stand=str(body.get("stand") or ""),
            atis_letter=str(body.get("atis_letter") or ""),
        )
        self.runtime.emit_event("new_messages", {"count": 1})
        return {"ok": True, "message": _message_dict(stored)}


def error_payload(exc: BaseException) -> tuple[int, dict[str, Any]]:
    if isinstance(exc, KeyError):
        return 404, {"ok": False, "error": str(exc)}
    if isinstance(exc, SendNotAllowedError):
        return 403, {"ok": False, "error": str(exc)}
    if isinstance(exc, (HoppieError, ValueError)):
        return 400, {"ok": False, "error": str(exc)}
    return 500, {"ok": False, "error": str(exc)}


def dumps(data: Any) -> bytes:
    return json.dumps(data, default=str).encode("utf-8")
