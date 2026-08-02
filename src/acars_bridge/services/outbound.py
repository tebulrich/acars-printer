from __future__ import annotations

from acars_bridge.hoppie.cpdlc import CpdlcPacket
from acars_bridge.hoppie.errors import HoppieError, SendNotAllowedError
from acars_bridge.hoppie.parser import parse_response
from acars_bridge.hoppie.requests import (
    AtisSide,
    AtisSource,
    WeatherKind,
    build_atis_packet,
    build_pdc_telex,
    build_position_packet,
    build_weather_packet,
    normalize_icao,
)
from acars_bridge.hoppie.station import StationTransport
from acars_bridge.hoppie.types import MessageType
from acars_bridge.models.messages import MessageRepository, StoredMessage
from acars_bridge.models.settings import SettingsStore
from acars_bridge.services.ingestion import MessageIngestionService


class OutboundMessageService:
    def __init__(
        self,
        station: StationTransport,
        repo: MessageRepository,
        settings: SettingsStore,
        ingestion: MessageIngestionService | None = None,
    ) -> None:
        self._station = station
        self._repo = repo
        self._settings = settings
        self._ingestion = ingestion

    def send_telex(self, to: str, text: str) -> StoredMessage:
        logon, callsign = self._require_credentials()
        raw = self._station.send_telex(logon, callsign, to, text)
        self._ensure_ok(raw)
        return self._repo.insert_outbound(
            callsign=callsign,
            to_station=to.strip().upper(),
            message_type=MessageType.TELEX,
            body=text,
            raw_payload=raw,
            send_status="sent",
        )

    def reply_cpdlc(self, message_id: int, reply: str) -> StoredMessage:
        logon, callsign = self._require_credentials()
        inbound = self._repo.get(message_id)
        if inbound is None:
            raise HoppieError(f"Message {message_id} not found.")
        if inbound.direction != "in" or inbound.message_type != MessageType.CPDLC.value:
            raise HoppieError("Can only reply to inbound CPDLC messages.")
        if not inbound.sender:
            raise HoppieError("Inbound CPDLC message has no sender to reply to.")

        our_min = self._settings.next_downlink_min()
        packet = CpdlcPacket.build_reply(
            our_min=our_min,
            uplink_min=inbound.min,
            reply=reply,
        )
        raw = self._station.send_cpdlc(logon, callsign, inbound.sender, packet.encode())
        self._ensure_ok(raw)
        return self._repo.insert_outbound(
            callsign=callsign,
            to_station=inbound.sender,
            message_type=MessageType.CPDLC,
            body=packet.display_text,
            raw_payload=packet.encode(),
            min_id=packet.min,
            mrn=packet.mrn,
            ra=packet.ra,
            send_status="sent",
        )

    def request_weather(self, kind: WeatherKind | str, icao: str) -> list[StoredMessage]:
        packet = build_weather_packet(kind, icao)
        return self._request_inforeq(packet, label=str(kind).upper())

    def request_atis(
        self,
        icao: str,
        *,
        source: AtisSource | str = AtisSource.VATSIM,
        side: AtisSide | str | None = AtisSide.DEP,
        fallback_plain: bool = True,
    ) -> list[StoredMessage]:
        primary = build_atis_packet(icao, source=source, side=side)
        stored = self._request_inforeq(primary, label="ATIS")
        if stored or not fallback_plain or side is None:
            return stored
        # Split D/A ATIS may be offline; retry airport ICAO only.
        plain = build_atis_packet(icao, source=source, side=None)
        if plain == primary:
            return stored
        return self._request_inforeq(plain, label="ATIS")

    def request_pdc(
        self,
        *,
        station: str,
        departure: str,
        destination: str,
        aircraft_type: str,
        stand: str,
        atis_letter: str,
    ) -> StoredMessage:
        logon, callsign = self._require_credentials()
        to = station.strip().upper()
        if not to:
            raise HoppieError("PDC station is required.")
        body = build_pdc_telex(
            callsign=callsign,
            aircraft_type=aircraft_type,
            destination=destination,
            departure=departure,
            stand=stand,
            atis_letter=atis_letter,
        )
        raw = self._station.send_telex(logon, callsign, to, body)
        self._ensure_ok(raw)
        self._settings.set("req_pdc_station", to)
        self._settings.set("req_pdc_dep", normalize_icao(departure))
        self._settings.set("req_pdc_dest", normalize_icao(destination))
        self._settings.set("req_pdc_actype", aircraft_type.strip().upper())
        self._settings.set("req_pdc_stand", stand.strip().upper())
        self._settings.set("req_pdc_atis", atis_letter.strip().upper())
        return self._repo.insert_outbound(
            callsign=callsign,
            to_station=to,
            message_type=MessageType.TELEX,
            body=body,
            raw_payload=raw,
            send_status="sent",
        )

    def send_position(
        self,
        *,
        to: str,
        latitude: str,
        longitude: str,
        altitude: str,
        time_utc: str,
        next_waypoint: str | None = None,
        eta: str | None = None,
        remark: str | None = None,
    ) -> StoredMessage:
        logon, callsign = self._require_credentials()
        dest = to.strip().upper()
        if not dest:
            raise HoppieError("Position report destination is required.")
        packet = build_position_packet(
            latitude=latitude,
            longitude=longitude,
            altitude=altitude,
            time_utc=time_utc,
            next_waypoint=next_waypoint,
            eta=eta,
            remark=remark,
        )
        raw = self._station.send_position(logon, callsign, dest, packet)
        self._ensure_ok(raw)
        self._settings.set("req_pos_to", dest)
        return self._repo.insert_outbound(
            callsign=callsign,
            to_station=dest,
            message_type=MessageType.POSITION,
            body=packet,
            raw_payload=raw,
            send_status="sent",
        )

    def _request_inforeq(self, packet: str, *, label: str) -> list[StoredMessage]:
        logon, callsign = self._require_credentials()
        raw = self._station.send_inforeq(logon, callsign, packet)
        messages = parse_response(raw if raw.strip() else "ok", callsign)
        outbound = self._repo.insert_outbound(
            callsign=callsign,
            to_station="SERVER",
            message_type=MessageType.INFOREQ,
            body=f"{label}: {packet}",
            raw_payload=raw,
            send_status="sent",
        )
        icao = packet.split()[-1].split("_")[0] if packet.split() else ""
        if icao and len(icao) == 4:
            self._settings.set("req_last_icao", icao)
        if not messages:
            return [outbound]
        if self._ingestion is None:
            return [outbound]
        self._ingestion.ingest(messages)
        recent = self._repo.list_recent(max(5, len(messages) + 1))
        inbound = [row for row in recent if row.direction == "in"][: len(messages)]
        return [outbound, *inbound]

    def _require_credentials(self) -> tuple[str, str]:
        logon = self._settings.hoppie_logon()
        callsign = self._settings.callsign()
        if not logon or not callsign:
            raise HoppieError("Configure hoppie logon and callsign first.")
        if self._settings.mode().value == "observer":
            raise SendNotAllowedError(
                "Observer mode cannot send. Switch to Station mode first."
            )
        return logon, callsign

    def _ensure_ok(self, raw: str) -> None:
        # Reuse parser for error detection; ignore returned messages.
        parse_response(raw if raw.strip() else "ok", self._settings.callsign() or "TEST")
