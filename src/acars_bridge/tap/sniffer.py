"""Passive Hoppie HTTP sniffer.

Fenix (and others) often keep a cached Hoppie IP after DNS lookup, so a hosts-file
redirect never sees them. This sniffer watches the real Hoppie IPv4 and pulls
plain HTTP request/response bodies out of the packet stream.
"""

from __future__ import annotations

import logging
import socket
import struct
import threading
from collections.abc import Callable
from urllib.parse import parse_qs

log = logging.getLogger(__name__)

FormHandler = Callable[[dict[str, str], str], None]


class HoppieHttpSniffer:
    def __init__(self, hoppie_ip: str, on_exchange: FormHandler) -> None:
        self._hoppie_ip = hoppie_ip
        self._on_exchange = on_exchange
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.packets_seen = 0
        self.http_hits = 0
        self.last_error: str | None = None
        self._streams: dict[tuple, bytearray] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._sock = self._open_socket()
        self._thread = threading.Thread(
            target=self._loop, name="hoppie-http-sniffer", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        sock = getattr(self, "_sock", None)
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        self._streams.clear()

    def _open_socket(self) -> socket.socket:
        host = socket.gethostbyname(socket.gethostname())
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
        sock.bind((host, 0))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
        sock.settimeout(1.0)
        return sock

    def _loop(self) -> None:
        sock = getattr(self, "_sock", None)
        if sock is None:
            return
        try:
            while not self._stop.is_set():
                try:
                    data, _ = sock.recvfrom(65535)
                except TimeoutError:
                    continue
                except OSError:
                    break
                self.packets_seen += 1
                self._handle_ip(data)
        finally:
            try:
                sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
            self._sock = None

    def _handle_ip(self, data: bytes) -> None:
        if len(data) < 20:
            return
        ihl = (data[0] & 0x0F) * 4
        if ihl < 20 or len(data) < ihl + 4:
            return
        if data[9] != 6:  # TCP
            return
        src = socket.inet_ntoa(data[12:16])
        dst = socket.inet_ntoa(data[16:20])
        if src != self._hoppie_ip and dst != self._hoppie_ip:
            return
        tcp = data[ihl:]
        if len(tcp) < 20:
            return
        sport, dport = struct.unpack("!HH", tcp[0:4])
        doff = ((tcp[12] >> 4) & 0x0F) * 4
        payload = tcp[doff:]
        if not payload:
            return
        # Only care about Hoppie HTTP ports.
        if sport not in {80, 443} and dport not in {80, 443}:
            return
        # HTTPS is encrypted — skip. Plain HTTP is what we can print.
        if sport == 443 or dport == 443:
            return

        key = (src, sport, dst, dport)
        buf = self._streams.setdefault(key, bytearray())
        buf.extend(payload)
        if len(buf) > 1_000_000:
            self._streams.pop(key, None)
            return
        self._try_extract(key, buf)

    def _try_extract(self, key: tuple, buf: bytearray) -> None:
        text = bytes(buf)
        # Response from Hoppie (source is Hoppie).
        if key[0] == self._hoppie_ip and b"\r\n\r\n" in text:
            head, body = text.split(b"\r\n\r\n", 1)
            if not head.upper().startswith(b"HTTP/"):
                return
            if b"Content-Length:" in head:
                try:
                    cl_line = [
                        line
                        for line in head.split(b"\r\n")
                        if line.lower().startswith(b"content-length:")
                    ][0]
                    needed = int(cl_line.split(b":", 1)[1].strip())
                except (IndexError, ValueError):
                    needed = None
            else:
                needed = None
            if needed is not None and len(body) < needed:
                return
            if needed is not None:
                body = body[:needed]
            body_text = body.decode("utf-8", errors="replace")
            # Pair with the most recent request on the reverse tuple if present.
            rev = (key[2], key[3], key[0], key[1])
            req_buf = self._streams.get(rev, bytearray())
            form = _form_from_http_bytes(bytes(req_buf))
            self.http_hits += 1
            try:
                self._on_exchange(form, body_text)
            except Exception as exc:  # noqa: BLE001
                log.debug("sniffer exchange handler failed: %s", exc)
            self._streams.pop(key, None)
            self._streams.pop(rev, None)
            return

        # Request to Hoppie — keep buffering until we also see a response.
        if key[2] == self._hoppie_ip and (
            b"POST " in text[:32] or b"GET " in text[:32] or b"connect.html" in text
        ):
            return


def _form_from_http_bytes(raw: bytes) -> dict[str, str]:
    if b"\r\n\r\n" not in raw:
        # Maybe only body fragments with form fields.
        return _parse_qs_bytes(raw)
    head, body = raw.split(b"\r\n\r\n", 1)
    form: dict[str, str] = {}
    first = head.split(b"\r\n", 1)[0].decode("iso-8859-1", errors="replace")
    if " " in first:
        parts = first.split(" ")
        if len(parts) >= 2 and "?" in parts[1]:
            form.update(_parse_qs_bytes(parts[1].split("?", 1)[1].encode()))
    form.update(_parse_qs_bytes(body))
    return form


def _parse_qs_bytes(data: bytes) -> dict[str, str]:
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return {}
    # Trim to likely form payload.
    if "logon=" in text:
        text = text[text.index("logon=") :]
    elif "type=" in text:
        text = text[text.index("type=") :]
    parsed = parse_qs(text, keep_blank_values=True)
    return {k: (v[0] if v else "") for k, v in parsed.items()}
