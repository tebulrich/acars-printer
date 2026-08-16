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
from acars_bridge.hoppie.atis_pick import atis_side_from_snapshot
from acars_bridge.hoppie.ivao_atis import fetch_ivao_atis
from acars_bridge.hoppie.vatsim_atis import (
    fetch_vatsim_atis,
    hoppie_vatatis_packets,
    list_vatsim_atis,
)
from acars_bridge.models.messages import MessageRepository, StoredMessage
from acars_bridge.models.settings import SettingsStore
from acars_bridge.services.fingerprint import fingerprint_for
from acars_bridge.services.ingestion import MessageIngestionService
from acars_bridge.weather.awc import fetch_metar_raw, fetch_taf_raw


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
        self._session = None
        self.last_print_stats: dict[str, int] = {
            "stored": 0,
            "printed": 0,
            "duplicates": 0,
            "failed_prints": 0,
        }

    def attach_session(self, session: object) -> None:
        """Bind AppSession so callsign can auto-follow SimBrief / inbox."""
        self._session = session

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
        if self._hoppie_credentials() is None:
            return self._request_weather_public(kind, icao)
        packet = build_weather_packet(kind, icao)
        rows, _unavailable, _print_stats = self._request_inforeq(
            packet, label=str(kind).upper()
        )
        return rows

    def request_atis(
        self,
        icao: str,
        *,
        source: AtisSource | str | None = None,
        side: AtisSide | str | None = None,
        fallback_plain: bool = True,
    ) -> list[StoredMessage]:
        """Request ATIS from one network only (VATSIM or IVAO — never both).

        Combined if that network has it; else dep on ground / arrival in air.
        """
        if source is not None:
            self._settings.set_atis_source(source)
        source_value = self._settings.atis_source()
        resolved = side if side is not None else self._auto_atis_side()
        if source_value is AtisSource.VATSIM:
            return self._request_vatsim_atis(icao, side=resolved)
        if source_value is AtisSource.IVAO:
            return self._request_ivao_atis(icao, side=resolved)

        primary = build_atis_packet(icao, source=source_value, side=resolved)
        stored, unavailable, _stats = self._request_inforeq(primary, label="ATIS")
        if fallback_plain and resolved is not None and unavailable:
            plain = build_atis_packet(icao, source=source_value, side=None)
            if plain != primary:
                stored, _unavailable, _stats = self._request_inforeq(plain, label="ATIS")
        return stored

    def _auto_atis_side(self) -> AtisSide | None:
        snap = None
        if self._session is not None:
            monitor = getattr(self._session, "simconnect", None)
            getter = getattr(monitor, "snapshot", None)
            if callable(getter):
                snap = getter()
        return atis_side_from_snapshot(snap)

    def _request_vatsim_atis(
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
        if self._hoppie_credentials() is not None:
            for packet in hoppie_vatatis_packets(icao, side=side, online_callsigns=online):
                stored, unavailable, stats = self._request_inforeq(packet, label="ATIS")
                self.last_print_stats = stats
                if not unavailable:
                    return stored

        public = self._ingest_public_atis(
            icao, fetch_vatsim_atis, side=side, packet_prefix="vatsim-data"
        )
        if public is not None:
            return public
        if stored:
            return stored
        code = normalize_icao(icao)
        raise HoppieError(
            f"No VATSIM ATIS for {code}.",
            hint="Nobody is publishing ATIS there on VATSIM right now.",
        )

    def _request_ivao_atis(
        self,
        icao: str,
        *,
        side: AtisSide | str | None,
    ) -> list[StoredMessage]:
        public = self._ingest_public_atis(
            icao, fetch_ivao_atis, side=side, packet_prefix="ivao-data"
        )
        if public is not None:
            return public
        code = normalize_icao(icao)
        raise HoppieError(
            f"No IVAO ATIS for {code}.",
            hint="Nobody is publishing ATIS there on IVAO right now.",
        )

    def _ingest_public_atis(
        self,
        icao: str,
        fetch,
        *,
        side: AtisSide | str | None,
        packet_prefix: str,
    ) -> list[StoredMessage] | None:
        try:
            atis = fetch(icao, side=side)
        except Exception:
            return None
        if atis is None or not atis.has_text:
            return None
        code = normalize_icao(icao)
        return self._ingest_public_inforeq(
            packet=f"{packet_prefix} {atis.callsign}",
            body=atis.body(),
            sender=atis.callsign,
            label="ATIS",
            icao=code,
        )

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

    def _hoppie_credentials(self) -> tuple[str, str] | None:
        try:
            return self._require_credentials(allow_observer=True)
        except (SendNotAllowedError, HoppieError):
            return None

    def _observer_callsign(self) -> str:
        if self._session is not None:
            from acars_bridge.services.station_identity import resolve_station_identity

            identity = resolve_station_identity(self._session)
            if identity.callsign:
                return identity.callsign
        cs = (self._settings.callsign() or "").strip().upper()
        return cs or "FO"

    def _ingest_public_inforeq(
        self,
        *,
        packet: str,
        body: str,
        sender: str,
        label: str,
        icao: str,
    ) -> list[StoredMessage]:
        callsign = self._observer_callsign()
        if icao:
            self._settings.set("req_last_icao", icao)
        outbound = self._repo.insert_outbound(
            callsign=callsign,
            to_station=sender,
            message_type=MessageType.INFOREQ,
            body=f"{label}: {packet}",
            raw_payload=packet,
            send_status="sent",
        )
        message = HoppieMessage(
            callsign=callsign,
            sender=sender,
            recipient=callsign,
            message_type=MessageType.INFOREQ,
            raw_payload=packet,
            normalized_body=body,
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

    def _request_weather_public(
        self, kind: WeatherKind | str, icao: str
    ) -> list[StoredMessage]:
        kind_value = WeatherKind(str(kind).strip().lower())
        code = normalize_icao(icao)
        if kind_value is WeatherKind.METAR:
            text = fetch_metar_raw(code)
            label = "METAR"
        else:
            text = fetch_taf_raw(code)
            label = "TAF" if kind_value is WeatherKind.TAF else "SHORTTAF"
        if not text:
            raise HoppieError(f"No {label} for {code}.")
        packet = f"{kind_value.value} {code}"
        head = text.split("\n", 1)[0].strip().upper()
        body = text if head.startswith(label) else f"{label} {code}\n{text}"
        return self._ingest_public_inforeq(
            packet=packet,
            body=body,
            sender="AWC",
            label=label,
            icao=code,
        )

    def _require_credentials(self, *, allow_observer: bool = False) -> tuple[str, str]:
        from acars_bridge.services.station_identity import resolve_station_identity

        del allow_observer
        # Station mode: PC owns the callsign (settings logon + resolved callsign).
        if self._settings.companion_station_enabled():
            logon = self._settings.hoppie_logon()
            identity = (
                resolve_station_identity(self._session)
                if self._session is not None
                else None
            )
            callsign = identity.callsign if identity is not None else self._settings.callsign()
            if not logon:
                raise HoppieError(
                    "Set your Hoppie logon under Network.",
                    hint="Station mode needs the logon code on the PC.",
                )
            if not callsign:
                raise HoppieError(
                    "No callsign yet.",
                    hint="Load a SimBrief OFP, print one ACARS strip, or set the Network filter.",
                )
            return logon, callsign

        # Connect/tap MITM: reuse the aircraft’s live wire credentials (no poll).
        wire = None
        if self._session is not None:
            wire = self._session.wire_session.get()
        if wire is not None:
            return wire.logon, wire.from_cs

        raise SendNotAllowedError(
            "Can't send from the phone yet.",
            hint="On the PC: Connect after the plane is on Hoppie, or turn on Companion station mode.",
        )

    def _ensure_ok(self, raw: str) -> None:
        # Reuse parser for error detection; ignore returned messages.
        parse_response(raw if raw.strip() else "ok", self._settings.callsign() or "TEST")
