from __future__ import annotations

import gzip

from acars_bridge.tap.proxy import (
    _decode_response_body,
    _force_identity_encoding,
    _form_from_http,
    _inject_from_callsign,
    _looks_like_hoppie,
    _patch_hoppie_credentials,
)


def test_force_identity_encoding_replaces_accept_encoding() -> None:
    head = (
        b"GET /acars/system/connect.html?type=poll HTTP/1.1\r\n"
        b"Host: www.hoppie.nl\r\n"
        b"Accept-Encoding: gzip, deflate, br\r\n"
        b"Connection: close\r\n"
        b"\r\n"
    )
    out = _force_identity_encoding(head)
    text = out.decode("iso-8859-1")
    assert out.endswith(b"\r\n\r\n")
    assert "Accept-Encoding: identity" in text
    assert "gzip" not in text.lower().split("accept-encoding:", 1)[1].split("\r\n", 1)[0]


def test_force_identity_encoding_injects_when_missing() -> None:
    head = (
        b"POST /acars/system/connect.html HTTP/1.1\r\n"
        b"Host: www.hoppie.nl\r\n"
        b"Content-Length: 48\r\n"
        b"\r\n"
    )
    out = _force_identity_encoding(head)
    assert out.endswith(b"\r\n\r\n")
    assert b"Accept-Encoding: identity\r\n\r\n" in out


def test_force_identity_encoding_preserves_body_boundary() -> None:
    """Regression: missing CRLFCRLF made Hoppie drop POST from/logon."""
    head = (
        b"POST /acars/system/connect.html HTTP/1.1\r\n"
        b"Host: www.hoppie.nl\r\n"
        b"Accept-Encoding: gzip\r\n"
        b"Content-Type: application/x-www-form-urlencoded\r\n"
        b"Content-Length: 64\r\n"
        b"\r\n"
    )
    body = b"logon=secret&from=DLH9911&to=SERVER&type=infoReq&packet=metar+EDDF"
    forwarded = _force_identity_encoding(head) + body
    header_end = forwarded.index(b"\r\n\r\n") + 4
    assert forwarded[header_end:] == body


def test_decode_response_body_gzip_header() -> None:
    plain = b"ok {SERVER inforeq {VATATIS EDDF unavailable}}"
    body = gzip.compress(plain)
    head = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Encoding: gzip\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"\r\n"
    )
    assert _decode_response_body(head, body) == plain.decode()


def test_decode_response_body_gzip_magic_without_header() -> None:
    plain = b"ok"
    body = gzip.compress(plain)
    head = b"HTTP/1.1 200 OK\r\n\r\n"
    assert _decode_response_body(head, body) == "ok"


def test_decode_response_body_plain() -> None:
    head = b"HTTP/1.1 200 OK\r\n\r\n"
    assert _decode_response_body(head, b"ok") == "ok"


def test_looks_like_hoppie_from_form() -> None:
    assert _looks_like_hoppie(
        {"type": "inforeq", "from": "DLH123"},
        "ok",
        "/acars/system/connect.html",
    )


def test_looks_like_hoppie_from_ok_body() -> None:
    assert _looks_like_hoppie({}, "ok {SERVER telex {hi}}", "/acars/system/connect.html")
    assert not _looks_like_hoppie({}, "<html>hoppie</html>", "/acars/system/index.html")
    assert not _looks_like_hoppie({}, "ok", "/favicon.ico")


def test_inject_from_callsign_fills_empty_query_from() -> None:
    head = (
        b"GET /acars/system/connect.html?logon=wronguser&from=&to=SERVER"
        b"&type=infoReq&packet=metar+EDDH HTTP/1.1\r\n"
        b"Host: www.hoppie.nl\r\n"
        b"\r\n"
    )
    new_head, new_body = _inject_from_callsign(head, b"", "DLH9911")
    assert new_body == b""
    form = _form_from_http(new_head, new_body)
    assert form["from"] == "DLH9911"
    assert form["packet"] == "metar EDDH"
    assert form["logon"] == "wronguser"
    assert b"from=DLH9911" in new_head


def test_inject_from_callsign_leaves_existing_from() -> None:
    head = (
        b"GET /acars/system/connect.html?logon=x&from=AAL123&to=SERVER"
        b"&type=poll&packet= HTTP/1.1\r\n"
        b"Host: www.hoppie.nl\r\n"
        b"\r\n"
    )
    new_head, _body = _inject_from_callsign(head, b"", "DLH9911")
    form = _form_from_http(new_head, b"")
    assert form["from"] == "AAL123"


def test_patch_does_not_rewrite_logon() -> None:
    head = (
        b"GET /acars/system/connect.html?logon=plane-logon&from=&to=SERVER"
        b"&type=infoReq&packet=metar+EDDH HTTP/1.1\r\n"
        b"Host: www.hoppie.nl\r\n"
        b"\r\n"
    )
    new_head, new_body, notes = _patch_hoppie_credentials(
        head,
        b"",
        fill_from="DLH9911",
    )
    form = _form_from_http(new_head, new_body)
    assert form["from"] == "DLH9911"
    assert form["logon"] == "plane-logon"
    assert any(n.startswith("from=") for n in notes)
    assert not any("logon" in n for n in notes)
