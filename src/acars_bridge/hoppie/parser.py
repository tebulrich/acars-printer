from __future__ import annotations

from acars_bridge.hoppie.cpdlc import CpdlcPacket
from acars_bridge.hoppie.errors import CallsignInUseError, HoppieError
from acars_bridge.hoppie.types import HoppieMessage, MessageType


def parse_response(raw_response: str, callsign: str) -> list[HoppieMessage]:
    body = raw_response.strip()
    if not body:
        raise HoppieError("Empty Hoppie response.")

    lower = body.lower()
    if lower.startswith("error"):
        detail = body[5:].strip()
        if "callsign already in use" in detail.lower():
            raise CallsignInUseError(detail or "callsign already in use")
        raise HoppieError(detail or "Hoppie returned an error.")

    if not lower.startswith("ok"):
        raise HoppieError("Malformed Hoppie response: missing ok/error status.")

    remainder = body[2:].lstrip()
    if not remainder:
        return []

    messages: list[HoppieMessage] = []
    for block in _extract_blocks(remainder):
        parsed = _parse_block(block, callsign)
        if parsed is not None:
            messages.append(parsed)
    return messages


def _extract_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    i = 0
    length = len(text)
    while i < length:
        while i < length and text[i].isspace():
            i += 1
        if i >= length:
            break
        if text[i] != "{":
            raise HoppieError("Malformed Hoppie response: expected message block.")
        depth = 0
        start = i
        while i < length:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(text[start + 1 : i])
                    i += 1
                    break
            i += 1
        if depth != 0:
            raise HoppieError("Malformed Hoppie response: unbalanced braces.")
    return blocks


def _parse_block(block: str, callsign: str) -> HoppieMessage | None:
    block = block.strip()
    # Optional undocumented numeric id prefix.
    parts = block.split(None, 1)
    if parts and parts[0].isdigit() and len(parts) == 2:
        block = parts[1]

    if " {" not in block or not block.endswith("}"):
        return None

    head, _, packet_with_brace = block.partition(" {")
    packet = packet_with_brace[:-1]
    head_parts = head.split(None, 1)
    if len(head_parts) != 2:
        return None

    sender, type_raw = head_parts
    message_type = MessageType.from_hoppie(type_raw)
    normalized = _normalize_body(packet, message_type)

    min_id = mrn = ra = None
    if message_type is MessageType.CPDLC:
        try:
            cpdlc = CpdlcPacket.parse(packet)
            min_id, mrn, ra = cpdlc.min, cpdlc.mrn, cpdlc.ra
            normalized = cpdlc.display_text
        except ValueError:
            pass

    callsign_u = callsign.upper()
    return HoppieMessage(
        callsign=callsign_u,
        sender=sender or None,
        recipient=callsign_u,
        message_type=message_type,
        raw_payload="{" + block + "}",
        normalized_body=normalized,
        min=min_id,
        mrn=mrn,
        ra=ra,
    )


def _normalize_body(packet: str, message_type: MessageType) -> str:
    body = packet.replace("\r\n", "\n").replace("\r", "\n")
    if message_type is MessageType.CPDLC:
        body = body.replace("@", "\n")
    lines = [line.rstrip() for line in body.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)
