from __future__ import annotations

import gzip
import logging
import select
import socket
import ssl
import threading
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

log = logging.getLogger(__name__)

ExchangeHandler = Callable[[dict[str, str], str], None]


@dataclass(slots=True)
class ProxyConfig:
    upstream_host: str
    upstream_ip: str
    http_port: int = 80
    https_port: int = 443
    server_cert: Path | None = None
    server_key: Path | None = None
    enable_https: bool = True
    # When the aircraft sends from= empty, fill this callsign before Hoppie sees it.
    fill_from_callsign: str | None = None


class HoppieForwardProxy:
    """Local reverse proxy: plane → us → real Hoppie, with response tap."""

    def __init__(
        self,
        config: ProxyConfig,
        on_exchange: ExchangeHandler,
        *,
        on_debug: Callable[[str], None] | None = None,
    ) -> None:
        self._config = config
        self._on_exchange = on_exchange
        self._on_debug = on_debug
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._sockets: list[socket.socket] = []
        self.exchanges = 0
        self.last_error: str | None = None

    def _debug(self, message: str) -> None:
        if self._on_debug:
            try:
                self._on_debug(message)
            except Exception:  # noqa: BLE001
                pass
        log.debug(message)

    def start(self) -> None:
        self._stop.clear()
        self._start_listener(self._config.http_port, tls=False)
        if (
            self._config.enable_https
            and self._config.server_cert
            and self._config.server_key
        ):
            try:
                self._start_listener(self._config.https_port, tls=True)
            except OSError as exc:
                # HTTP-only still useful; surface HTTPS bind failure.
                self.last_error = f"HTTPS listen failed on :{self._config.https_port}: {exc}"
                log.warning(self.last_error)

    def stop(self) -> None:
        self._stop.set()
        for sock in self._sockets:
            try:
                sock.close()
            except OSError:
                pass
        self._sockets.clear()
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads.clear()

    def _start_listener(self, port: int, *, tls: bool) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # 0.0.0.0: WinDivert reflection delivers to the LAN IP, not only loopback.
        # Hosts-file clients still reach us via 127.0.0.1 on the same socket.
        sock.bind(("0.0.0.0", port))
        sock.listen(64)
        sock.settimeout(1.0)
        self._sockets.append(sock)
        self._debug(f"listening {'https' if tls else 'http'} on 0.0.0.0:{port}")
        thread = threading.Thread(
            target=self._accept_loop,
            args=(sock, tls),
            name=f"hoppie-tap-{'https' if tls else 'http'}",
            daemon=True,
        )
        thread.start()
        self._threads.append(thread)

    def _accept_loop(self, listen_sock: socket.socket, tls: bool) -> None:
        while not self._stop.is_set():
            try:
                client, addr = listen_sock.accept()
            except TimeoutError:
                continue
            except OSError:
                if self._stop.is_set():
                    break
                continue
            self._debug(f"accept tls={tls} peer={addr[0]}:{addr[1]}")
            worker = threading.Thread(
                target=self._handle_client,
                args=(client, tls),
                daemon=True,
            )
            worker.start()

    def _handle_client(self, client: socket.socket, tls: bool) -> None:
        upstream: socket.socket | None = None
        try:
            if tls:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                assert self._config.server_cert and self._config.server_key
                context.load_cert_chain(
                    str(self._config.server_cert), str(self._config.server_key)
                )
                client = context.wrap_socket(client, server_side=True)
                self._debug("tls handshake ok")

            request = _recv_http_message(client)
            if request is None:
                self._debug("client closed before http request")
                return

            head, body = request
            form = _form_from_http(head, body)
            req_path = _request_path(head)
            if "connect.html" in req_path.lower() and (
                form.get("type") or form.get("logon") or form.get("packet")
            ):
                head, body, notes = _patch_hoppie_credentials(
                    head,
                    body,
                    fill_from=(self._config.fill_from_callsign or "").strip().upper()
                    or None,
                )
                if notes:
                    form = _form_from_http(head, body)
                    self._debug("patched " + ", ".join(notes))

            self._debug(
                f"http req type={form.get('type') or '-'} "
                f"from={form.get('from') or '-'} "
                f"logon={'set' if form.get('logon') else '-'} "
                f"body_len={len(body)}"
            )

            # Reach real Hoppie over HTTPS:443 using a reserved local source
            # port so WinDivert does not bounce us back into ourselves.
            upstream = _connect_upstream(self._config.upstream_ip)
            up_ctx = ssl.create_default_context()
            upstream = up_ctx.wrap_socket(
                upstream, server_hostname=self._config.upstream_host
            )

            # Forward request (possibly with from= filled). Do not rewrite
            # Accept-Encoding — that previously broke POST framing.
            upstream.sendall(head + body)
            response = _recv_http_message(upstream)
            if response is None:
                return
            resp_head, resp_body = response
            client.sendall(resp_head + resp_body)

            try:
                text = _decode_response_body(resp_head, resp_body)
            except Exception as exc:  # noqa: BLE001
                self._debug(f"tap decode failed: {exc}")
                return

            if not _looks_like_hoppie(form, text, req_path):
                kind = "gzip" if resp_body.startswith(b"\x1f\x8b") else (
                    "png" if resp_body.startswith(b"\x89PNG") else "other"
                )
                self._debug(
                    f"ignored non-hoppie http type={form.get('type')!r} "
                    f"path={req_path[:60]!r} kind={kind}"
                )
                return

            self.exchanges += 1
            keys = ",".join(sorted(form.keys()))
            nonempty = ",".join(sorted(k for k, v in form.items() if v))
            self._debug(
                f"hoppie exchange type={form.get('type') or '-'} "
                f"from={form.get('from') or '-'} "
                f"to={form.get('to') or '-'} "
                f"packet={(form.get('packet') or '')[:40]!r} "
                f"keys={keys or '-'} nonempty={nonempty or '-'} "
                f"body_len={len(body)} body={_redact_form_body(body)} "
                f"resp={text[:80]!r}"
            )
            try:
                self._on_exchange(form, text)
            except Exception as exc:  # noqa: BLE001
                self._debug(f"tap parse failed: {exc}")
        except ssl.SSLError as exc:
            self.last_error = f"TLS handshake failed (CA trust?): {exc}"
            self._debug(self.last_error)
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            self._debug(f"tap client error: {exc}")
        finally:
            try:
                client.close()
            except OSError:
                pass
            if upstream is not None:
                try:
                    upstream.close()
                except OSError:
                    pass


def _recv_http_message(sock: socket.socket) -> tuple[bytes, bytes] | None:
    """Read one HTTP message (headers + body) from sock."""
    data = bytearray()
    sock.settimeout(20)
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(65536)
        if not chunk:
            return None
        data.extend(chunk)
        if len(data) > 2_000_000:
            return None
    header_blob, rest = bytes(data).split(b"\r\n\r\n", 1)
    headers = header_blob.decode("iso-8859-1", errors="replace")
    content_length = _header_value(headers, "Content-Length")
    body = rest
    if content_length is not None:
        needed = int(content_length)
        while len(body) < needed:
            chunk = sock.recv(65536)
            if not chunk:
                break
            body += chunk
        body = body[:needed]
    else:
        # No length: for requests, body may be empty; for responses read until close/timeout.
        if headers.upper().startswith("HTTP/"):
            sock.settimeout(0.35)
            try:
                while True:
                    ready, _, _ = select.select([sock], [], [], 0.35)
                    if not ready:
                        break
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    body += chunk
            except (TimeoutError, OSError):
                pass
    return header_blob + b"\r\n\r\n", body


def _header_value(headers: str, name: str) -> str | None:
    target = name.lower() + ":"
    for line in headers.split("\r\n"):
        if line.lower().startswith(target):
            return line.split(":", 1)[1].strip()
    return None


def _form_from_http(head: bytes, body: bytes) -> dict[str, str]:
    from acars_bridge.tap.extract import parse_form_body

    headers = head.decode("iso-8859-1", errors="replace")
    # Query string on GET
    first = headers.split("\r\n", 1)[0]
    form: dict[str, str] = {}
    if " " in first:
        _method, path, *_rest = first.split(" ")
        if "?" in path:
            _merge_form(form, parse_form_body(path.split("?", 1)[1]))
    if body:
        _merge_form(form, parse_form_body(body))
    return form


def _merge_form(dst: dict[str, str], src: dict[str, str]) -> None:
    """Merge form fields; non-empty values win so blank query keys don't wipe POST."""
    for key, value in src.items():
        if not value and dst.get(key):
            continue
        dst[key] = value


def _patch_hoppie_credentials(
    head: bytes,
    body: bytes,
    *,
    fill_from: str | None,
) -> tuple[bytes, bytes, list[str]]:
    """Fill empty from= with the configured callsign filter when set."""
    notes: list[str] = []
    if not fill_from:
        return head, body, notes

    headers = head.decode("iso-8859-1", errors="replace")
    if not headers.endswith("\r\n\r\n"):
        headers = headers.rstrip("\r\n") + "\r\n\r\n"
    lines = headers.split("\r\n")
    while lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return head, body, notes

    first = lines[0]
    parts = first.split(" ")
    changed_any = False
    if len(parts) >= 2 and "?" in parts[1]:
        path, _, query = parts[1].partition("?")
        new_query, q_notes = _form_patch_fields(query, fill_from=fill_from)
        if q_notes:
            parts[1] = f"{path}?{new_query}"
            lines[0] = " ".join(parts)
            notes.extend(q_notes)
            changed_any = True

    new_body = body
    if body:
        body_text = body.decode("utf-8", errors="replace")
        if "=" in body_text:
            new_text, b_notes = _form_patch_fields(body_text, fill_from=fill_from)
            if b_notes:
                new_body = new_text.encode("utf-8")
                for note in b_notes:
                    if note not in notes:
                        notes.append(note)
                changed_any = True

    if not changed_any:
        return head, body, notes

    out_headers: list[str] = []
    for i, line in enumerate(lines):
        if i > 0 and line.lower().startswith("content-length:"):
            out_headers.append(f"Content-Length: {len(new_body)}")
        else:
            out_headers.append(line)
    out_headers.append("")
    out_headers.append("")
    return ("\r\n".join(out_headers)).encode("iso-8859-1"), new_body, notes


def _form_patch_fields(
    urlencoded: str,
    *,
    fill_from: str | None,
) -> tuple[str, list[str]]:
    pairs = parse_qsl(urlencoded, keep_blank_values=True)
    if not pairs and not urlencoded:
        return urlencoded, []
    notes: list[str] = []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    for key, value in pairs:
        key_l = key.lower()
        seen.add(key_l)
        if key_l == "from" and fill_from and not value.strip():
            out.append((key, fill_from))
            notes.append(f"from={fill_from}")
        else:
            out.append((key, value))

    if fill_from and "from" not in seen:
        out.append(("from", fill_from))
        notes.append(f"from={fill_from}")

    if not notes:
        return urlencoded, []
    return urlencode(out, doseq=True), notes


# Back-compat alias used by older tests / imports.
def _inject_from_callsign(head: bytes, body: bytes, callsign: str) -> tuple[bytes, bytes]:
    new_head, new_body, _notes = _patch_hoppie_credentials(head, body, fill_from=callsign)
    return new_head, new_body


def _redact_form_body(body: bytes, limit: int = 160) -> str:
    """Safe debug preview of a urlencoded body (logon redacted)."""
    if not body:
        return "-"
    text = body.decode("utf-8", errors="replace")
    parts: list[str] = []
    for piece in text.split("&"):
        if not piece:
            continue
        key, _, value = piece.partition("=")
        key_l = key.lower()
        if key_l == "logon":
            parts.append(f"{key}=***")
        else:
            parts.append(piece if len(piece) < 80 else piece[:77] + "...")
    preview = "&".join(parts)
    if len(preview) > limit:
        return preview[: limit - 3] + "..."
    return preview or "-"


def _force_identity_encoding(head: bytes) -> bytes:
    """Ask Hoppie for uncompressed bodies (protocol is plain text per tech.html).

    Aircraft clients often send Accept-Encoding: gzip; Hoppie's HTTP stack
    then returns Content-Encoding: gzip. We still forward whatever Hoppie
    sends unchanged to the plane — this only reshapes the upstream request.

    Critical: the returned header block must end with CRLFCRLF. A single
    trailing CRLF makes Hoppie treat the POST body as more headers, which
    drops ``from``/``logon`` and yields ``error {no from address}``.
    """
    headers = head.decode("iso-8859-1", errors="replace")
    if not headers.endswith("\r\n\r\n"):
        # _recv_http_message always returns head ending with CRLFCRLF.
        headers = headers.rstrip("\r\n") + "\r\n\r\n"
    lines = headers.split("\r\n")
    # split("\\r\\n") on a block ending in \\r\\n\\r\\n yields trailing empties;
    # drop them and re-terminate explicitly so join cannot eat the blank line.
    while lines and lines[-1] == "":
        lines.pop()
    out: list[str] = []
    saw_accept = False
    for i, line in enumerate(lines):
        if i > 0 and line.lower().startswith("accept-encoding:"):
            out.append("Accept-Encoding: identity")
            saw_accept = True
        else:
            out.append(line)
    if not saw_accept:
        out.append("Accept-Encoding: identity")
    # Blank line separating headers from body.
    out.append("")
    out.append("")
    return ("\r\n".join(out)).encode("iso-8859-1")


def _decode_response_body(head: bytes, body: bytes) -> str:
    """Decode Hoppie ACARS response text, undoing HTTP content-encoding."""
    headers = head.decode("iso-8859-1", errors="replace")
    encoding = (_header_value(headers, "Content-Encoding") or "").lower().strip()
    raw = body
    if encoding in {"gzip", "x-gzip"} or raw.startswith(b"\x1f\x8b"):
        raw = gzip.decompress(raw)
    elif encoding == "deflate":
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    elif encoding in {"br", "zstd"}:
        # Rare for Hoppie; leave opaque rather than inventing a decoder.
        raise ValueError(f"unsupported Content-Encoding: {encoding}")
    # Hoppie responses are ASCII/UTF-8 plain text ("ok", "ok {…}", "error …").
    return raw.decode("utf-8", errors="replace")


def _request_path(head: bytes) -> str:
    first = head.decode("iso-8859-1", errors="replace").split("\r\n", 1)[0]
    if " " not in first:
        return ""
    parts = first.split(" ")
    return parts[1] if len(parts) >= 2 else ""


def _looks_like_hoppie(form: dict[str, str], response_text: str, path: str = "") -> bool:
    # Only the connect API is ACARS; hosts redirect also pulls website assets.
    if "connect.html" not in path.lower():
        return False
    if not response_text or response_text.startswith(("\x1f\x8b", "\x89PNG")):
        return False
    if form.get("type") or form.get("logon") or form.get("packet"):
        return True
    lowered = response_text.lstrip().lower()
    return lowered.startswith(("ok", "error"))


def _connect_upstream(upstream_ip: str) -> socket.socket:
    """TCP connect to Hoppie:443 from a reserved local port (WinDivert bypass)."""
    from acars_bridge.tap.ports import PROXY_UPSTREAM_PORT_MAX, PROXY_UPSTREAM_PORT_MIN

    last_error: OSError | None = None
    for port in range(PROXY_UPSTREAM_PORT_MIN, PROXY_UPSTREAM_PORT_MAX + 1):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(20)
        try:
            sock.bind(("0.0.0.0", port))
            sock.connect((upstream_ip, 443))
            return sock
        except OSError as exc:
            last_error = exc
            try:
                sock.close()
            except OSError:
                pass
    raise OSError(
        f"Could not bind upstream port "
        f"{PROXY_UPSTREAM_PORT_MIN}-{PROXY_UPSTREAM_PORT_MAX}: {last_error}"
    )
