"""Discover LAN IPv4 addresses for companion URL display."""

from __future__ import annotations

import socket


def lan_ipv4_addresses() -> list[str]:
    """Best-effort non-loopback IPv4 addresses for this machine."""
    found: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    # UDP trick: discover the interface used for default route without sending.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127.") and ip not in found:
            found.insert(0, ip)
    except OSError:
        pass
    return found


def primary_lan_ip() -> str:
    ips = lan_ipv4_addresses()
    return ips[0] if ips else "127.0.0.1"
