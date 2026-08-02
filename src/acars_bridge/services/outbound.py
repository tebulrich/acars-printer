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
from acars_bridge.hoppie.types import HoppieMessage, MessageType
from acars_bridge.hoppie.vatsim_atis import (
    fetch_vatsim_atis,
    hoppie_vatatis_packets,
    list_vatsim_atis,
)
from acars_bridge.models.messages import MessageRepository, StoredMessage
from acars_bridge.models.settings import SettingsStore
from acars_bridge.services.fingerprint import fingerprint_for
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
        self.last_print_stats: dict[str, int] = {
            "stored": 0,
            "printed": 0,
            "duplicates": 0,
            "failed_prints": 0,
        }

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
        rows, _unavailable, _print_stats = self._request_inforeq(
            packet, label=str(kind).upper()
        )
        return rows

    def request_atis(
        self,
        icao: str,
        *,
        source: AtisSource | str = AtisSource.VATSIM,
        side: AtisSide | str | None = AtisSide.DEP,
        fallback_plain: bool = True,
    ) -> list[StoredMessage]:
        """Request ATIS via Hoppie, with live VATSIM station awareness.

        VATSIM (Hoppie ``vatatis``):
        1. Look up which ``*_ATIS`` callsigns are online
        2. Ask Hoppie with the right packet — plain ``vatatis ICAO`` for combined
           stations (EDDN/EDDS). Only use ``ICAO_D_ATIS`` / ``_A_ATIS`` when that
           split station is actually online
        3. If Hoppie still fails, use the public VATSIM datafeed text
        """
        source_value = AtisSource(str(source).strip().lower())
        if source_value is AtisSource.VATSIM:
            return self._request_vatatis(icao, side=side)

        primary = build_atis_packet(icao, source=source_value, side=side)
        stored, unavailable, _stats = self._request_inforeq(primary, label="ATIS")
        if fallback_plain and side is not None and unavailable:
            plain = build_atis_packet(icao, source=source_value, side=None)
            if plain != primary:
                stored, _unavailable, _stats = self._request_inforeq(plain, label="ATIS")
        return stored

    def _request_vatatis(
        self,
        icao: str,
        *,
        side: AtisSide | str | None,
    ) -> list[StoredMessage]:
        online: set[str] = set()
        try:
            online = {row.callsign for row in list_vatsim_atis(icao)}
        except Exception:
            online = set()

        stored: list[StoredMessage] = []
        for packet in hoppie_vatatis_packets(icao, side=side, online_callsigns=online):
            stored, unavailable, stats = self._request_inforeq(packet, label="ATIS")
            self.last_print_stats = stats
            if not unavailable:
                return stored

        # Only use the live datafeed when a station is online *with text*.
        # Never resurrect an older ATIS from our local message DB.
        if online:
            fallback = self._request_atis_vatsim_fallback(icao, side=side)
            if fallback is not None:
                return fallback
        return stored

    def _request_atis_vatsim_fallback(
        self,
        icao: str,
        *,
        side: AtisSide | str | None,
    ) -> list[StoredMessage] | None:
        try:
            atis = fetch_vatsim_atis(icao, side=side)
        except Exception:
            return None
        if atis is None or not atis.has_text:
            return None

        _logon, callsign = self._require_credentials(allow_observer=True)
        code = normalize_icao(icao)
        self._settings.set("req_last_icao", code)
        packet = f"vatsim-data {atis.callsign}"
        outbound = self._repo.insert_outbound(
            callsign=callsign,
            to_station="VATSIM",
            message_type=MessageType.INFOREQ,
            body=f"ATIS: {packet}",
            raw_payload=packet,
            send_status="sent",
        )
        message = HoppieMessage(
            callsign=callsign,
            sender=atis.callsign,
            recipient=callsign,
            message_type=MessageType.INFOREQ,
            raw_payload=packet,
            normalized_body=atis.body(),
        )
        if self._ingestion is None:
            self.last_print_stats = {
                "stored": 0,
                "printed": 0,
                "duplicates": 0,
                "failed_prints": 0,
            }
            return [outbound]
        self.last_print_stats = self._ingestion.ingest(
            [message], auto_print=True, force_print=True
        )
        stored = self._repo.get_by_fingerprint(fingerprint_for(message))
        return [outbound, stored] if stored is not None else [outbound]

    @staticmethod
    def _atis_body_unavailable(body: str) -> bool:
        from acars_bridge.hoppie.atis_text import atis_reply_unavailable

        return atis_reply_unavailable(body)

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

    def _request_inforeq(
        self, packet: str, *, label: str
    ) -> tuple[list[StoredMessage], bool, dict[str, int]]:
        """Send inforeq. Returns (rows, unavailable, print_stats).

        ``unavailable`` is derived from *this* Hoppie reply body — never from
        older matching messages already in the local DB (duplicate fingerprints
        previously made ATIS look online when Hoppie said it was not).
        """
        # Weather / ATIS inforeq is allowed in Observer (same Hoppie logon as the
        # aircraft client). Telex/CPDLC/PDC stay Station-only.
        logon, callsign = self._require_credentials(allow_observer=True)
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

        unavailable = not messages or any(
            self._atis_body_unavailable(msg.normalized_body) for msg in messages
        )
        empty_stats = {"stored": 0, "printed": 0, "duplicates": 0, "failed_prints": 0}
        if not messages:
            return [outbound], True, empty_stats

        print_stats = empty_stats
        if self._ingestion is not None:
            # User-triggered request: always print a real reply (even duplicates).
            # Skip printing unavailable stubs.
            print_stats = self._ingestion.ingest(
                messages,
                auto_print=not unavailable,
                force_print=not unavailable,
            )
        self.last_print_stats = print_stats

        inbounds: list[StoredMessage] = []
        for msg in messages:
            stored = self._repo.get_by_fingerprint(fingerprint_for(msg))
            if stored is not None:
                inbounds.append(stored)
        return [outbound, *inbounds], unavailable, print_stats

    def _require_credentials(self, *, allow_observer: bool = False) -> tuple[str, str]:
        del allow_observer  # Print-bridge never sends; signature kept for call sites.
        logon = self._settings.hoppie_logon()
        callsign = self._settings.callsign()
        if not logon or not callsign:
            raise HoppieError("Configure hoppie logon and callsign first.")
        raise SendNotAllowedError(
            "This app is Observer-only: it peeks and prints. "
            "Send weather / telex / CPDLC from the aircraft client."
        )

    def _ensure_ok(self, raw: str) -> None:
        # Reuse parser for error detection; ignore returned messages.
        parse_response(raw if raw.strip() else "ok", self._settings.callsign() or "TEST")
