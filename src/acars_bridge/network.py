"""ACARS network providers (Hoppie, SayIntentions.AI).

SayIntentions exposes a drop-in Hoppie-protocol endpoint:
https://kb.sayintentions.ai/article/integrate-with-sayintentions-ai-acars-cpdlc

Both networks use the same coexistence model:

- **No hosts-file redirect** — browsers and companion apps keep a direct path.
- **WinDivert only for flight-sim processes** — aircraft ACARS is MITM'd; the
  Hoppie website and SayIntentions companion app are left alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# Substrings matched against the TCP owner's executable basename (lowercase).
_SIM_PROCESS_ALLOWLIST = (
    "flightsimulator",
    "prepar3d",
    "x-plane",
    "xplane",
    "fsx",
    "p3d",
)

_SAYINTENTIONS_DENYLIST = (
    "sayintentions",
    "say-intentions",
)


class AcarsNetwork(StrEnum):
    HOPPIE = "hoppie"
    SAYINTENTIONS = "sayintentions"


@dataclass(frozen=True, slots=True)
class NetworkProfile:
    """Immutable tap + upstream identity for one ACARS network."""

    id: AcarsNetwork
    label: str
    """Human label for Settings."""

    primary_host: str
    """Hostname used for DNS resolve, TLS SNI, and Host/CN preference."""

    tap_hosts: tuple[str, ...]
    """Hostnames covered by the MITM certificate (hosts redirect when enabled)."""

    connect_path: str = "/acars/system/connect.html"
    hosts_redirect: bool = False
    """Install hosts-file redirect to 127.0.0.1 while Connected (off by default)."""

    divert_process_allowlist: tuple[str, ...] = ()
    """When non-empty, only these process name substrings are diverted."""

    divert_process_denylist: tuple[str, ...] = ()
    """Never divert these process name substrings."""

    @property
    def connect_url(self) -> str:
        return f"https://{self.primary_host}{self.connect_path}"


_PROFILES: dict[AcarsNetwork, NetworkProfile] = {
    AcarsNetwork.HOPPIE: NetworkProfile(
        id=AcarsNetwork.HOPPIE,
        label="Hoppie",
        primary_host="www.hoppie.nl",
        tap_hosts=("www.hoppie.nl", "hoppie.nl"),
        hosts_redirect=False,
        divert_process_allowlist=_SIM_PROCESS_ALLOWLIST,
    ),
    AcarsNetwork.SAYINTENTIONS: NetworkProfile(
        id=AcarsNetwork.SAYINTENTIONS,
        label="SayIntentions.AI",
        primary_host="acars.sayintentions.ai",
        tap_hosts=("acars.sayintentions.ai",),
        hosts_redirect=False,
        divert_process_allowlist=_SIM_PROCESS_ALLOWLIST,
        divert_process_denylist=_SAYINTENTIONS_DENYLIST,
    ),
}


DEFAULT_NETWORK = AcarsNetwork.HOPPIE


def parse_network(value: str | AcarsNetwork | None) -> AcarsNetwork:
    if isinstance(value, AcarsNetwork):
        return value
    raw = (value or "").strip().lower()
    if not raw:
        return DEFAULT_NETWORK
    try:
        return AcarsNetwork(raw)
    except ValueError:
        return DEFAULT_NETWORK


def profile_for(network: AcarsNetwork | str | None) -> NetworkProfile:
    return _PROFILES[parse_network(network)]


def all_profiles() -> tuple[NetworkProfile, ...]:
    return tuple(_PROFILES[n] for n in AcarsNetwork)


def all_tap_hosts() -> tuple[str, ...]:
    """Union of every provider hostname — used for the local MITM certificate SAN."""
    seen: list[str] = []
    for profile in all_profiles():
        for host in profile.tap_hosts:
            if host not in seen:
                seen.append(host)
    return tuple(seen)
