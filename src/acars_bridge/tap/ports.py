"""Shared port constants for the local Hoppie tap."""

from __future__ import annotations

# Local source ports the forwarder binds when calling real Hoppie:443.
# WinDivert must NOT redirect these, or the proxy loops onto itself.
PROXY_UPSTREAM_PORT_MIN = 41700
PROXY_UPSTREAM_PORT_MAX = 41799
