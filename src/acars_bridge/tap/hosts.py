from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from acars_bridge.network import profile_for

MARKER_BEGIN = "# acars-bridge-tap BEGIN"
MARKER_END = "# acars-bridge-tap END"
# Default hosts (Hoppie) — prefer passing ``hosts=`` from the active profile.
TAP_HOSTS = profile_for("hoppie").tap_hosts


def hosts_path() -> Path:
    if os.name == "nt":
        root = os.environ.get("SystemRoot", r"C:\Windows")
        return Path(root) / "System32" / "drivers" / "etc" / "hosts"
    return Path("/etc/hosts")


def is_tap_installed(text: str | None = None) -> bool:
    body = text if text is not None else hosts_path().read_text(encoding="utf-8", errors="replace")
    return MARKER_BEGIN in body and MARKER_END in body


def render_block(
    redirect_ip: str = "127.0.0.1",
    *,
    hosts: Sequence[str] | None = None,
) -> str:
    names = tuple(hosts) if hosts is not None else TAP_HOSTS
    lines = [
        MARKER_BEGIN,
        "# Route ACARS upstream through ACARS Print Bridge (local forwarder).",
    ]
    for host in names:
        lines.append(f"{redirect_ip} {host}")
    lines.append(MARKER_END)
    return "\n".join(lines) + "\n"


def install_tap_hosts(
    *,
    redirect_ip: str = "127.0.0.1",
    hosts: Sequence[str] | None = None,
) -> None:
    path = hosts_path()
    original = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    cleaned = remove_tap_block(original)
    if not cleaned.endswith("\n"):
        cleaned += "\n"
    path.write_text(
        cleaned + "\n" + render_block(redirect_ip, hosts=hosts),
        encoding="utf-8",
    )


def remove_tap_hosts() -> None:
    path = hosts_path()
    if not path.exists():
        return
    original = path.read_text(encoding="utf-8", errors="replace")
    cleaned = remove_tap_block(original).rstrip() + "\n"
    path.write_text(cleaned, encoding="utf-8")


def remove_tap_block(text: str) -> str:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped == MARKER_BEGIN:
            skipping = True
            continue
        if stripped == MARKER_END:
            skipping = False
            continue
        if not skipping:
            out.append(line)
    return "".join(out)
