from __future__ import annotations

from urllib.parse import parse_qs

from acars_bridge.hoppie.parser import parse_response
from acars_bridge.hoppie.types import HoppieMessage, MessageType


def parse_form_body(body: bytes | str) -> dict[str, str]:
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    else:
        text = body
    parsed = parse_qs(text, keep_blank_values=True)
    # Hoppie field names are lowercase; normalize so Packet/packet both work.
    return {
        key.lower(): (values[0] if values else "")
        for key, values in parsed.items()
    }


def messages_from_hoppie_exchange(
    *,
    request_form: dict[str, str],
    response_text: str,
    callsign_filter: str | None = None,
) -> tuple[list[HoppieMessage], bool]:
    """Turn a plane↔Hoppie HTTP exchange into printable messages.

    Returns (messages, force_print). force_print is True for inline
    inforeq replies so repeated ATIS/METAR still print.
    """
    req_type = (request_form.get("type") or "").strip().lower()
    from_cs = (request_form.get("from") or "").strip().upper()
    filter_cs = (callsign_filter or "").strip().upper() or None

    if filter_cs and from_cs and from_cs != filter_cs:
        return [], False

    # Sniffed responses may lack a paired request form — infer from body.
    if not req_type and "acars info" in response_text.lower():
        req_type = "inforeq"
        from_cs = from_cs or (filter_cs or "UNKNOWN")

    if req_type in {"ping"}:
        return [], False

    # Sends from the plane normally return bare ok — nothing to print.
    if req_type in {"telex", "cpdlc", "progress", "position", "posreq", "datareq"}:
        # Still parse in case Hoppie stuffed a payload in (rare).
        try:
            messages = parse_response(response_text, from_cs or filter_cs or "UNKNOWN")
        except Exception:  # noqa: BLE001
            return [], False
        return _filter(messages, filter_cs), False

    try:
        messages = parse_response(response_text, from_cs or filter_cs or "UNKNOWN")
    except Exception:  # noqa: BLE001
        return [], False

    messages = _filter(messages, filter_cs)

    if req_type == "inforeq":
        # Inline weather/ATIS — print every time the plane asks.
        if not messages and response_text.strip().lower().startswith("ok"):
            # Some clients get plain text after ok with no braces; ignore empty.
            return [], False
        # Ensure callsign is the aircraft that asked.
        fixed: list[HoppieMessage] = []
        for msg in messages:
            if from_cs and msg.callsign != from_cs:
                fixed.append(
                    HoppieMessage(
                        callsign=from_cs,
                        sender=msg.sender or "SERVER",
                        recipient=from_cs,
                        message_type=msg.message_type
                        if msg.message_type is not MessageType.UNKNOWN
                        else MessageType.INFOREQ,
                        raw_payload=msg.raw_payload,
                        normalized_body=msg.normalized_body,
                        min=msg.min,
                        mrn=msg.mrn,
                        ra=msg.ra,
                    )
                )
            else:
                fixed.append(msg)
        # Keep the station/query (packet) with the reply — Hoppie website does too.
        packet = _request_packet_label(request_form.get("packet"))
        if packet:
            fixed = [_with_request_label(msg, packet) for msg in fixed]
        return fixed, True

    # poll / peek / unknown with message blocks
    return messages, False


def _request_packet_label(packet: str | None) -> str | None:
    label = " ".join((packet or "").split()).strip().upper()
    return label or None


def _with_request_label(message: HoppieMessage, label: str) -> HoppieMessage:
    body = message.normalized_body or ""
    if body.upper().startswith(label):
        return message
    return HoppieMessage(
        callsign=message.callsign,
        sender=message.sender,
        recipient=message.recipient,
        message_type=message.message_type,
        raw_payload=message.raw_payload,
        normalized_body=f"{label}\n{body}" if body else label,
        min=message.min,
        mrn=message.mrn,
        ra=message.ra,
    )


def _filter(messages: list[HoppieMessage], callsign: str | None) -> list[HoppieMessage]:
    if not callsign:
        return messages
    return [
        m
        for m in messages
        if m.callsign.upper() == callsign
        or (m.recipient or "").upper() == callsign
        or (m.sender or "").upper() == callsign
    ]
