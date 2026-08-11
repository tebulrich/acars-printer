"""PIN / bearer auth for the companion web UI."""

from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse


def extract_token(handler: BaseHTTPRequestHandler) -> str | None:
    auth = handler.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    header = handler.headers.get("X-Companion-Token")
    if header and header.strip():
        return header.strip()
    parsed = urlparse(handler.path)
    qs = parse_qs(parsed.query)
    values = qs.get("token") or []
    if values and values[0].strip():
        return values[0].strip()
    return None


def token_ok(provided: str | None, expected: str) -> bool:
    if not provided or not expected:
        return False
    left = provided.encode("utf-8")
    right = expected.encode("utf-8")
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)
