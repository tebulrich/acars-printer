from __future__ import annotations

from acars_bridge.network import (
    DEFAULT_NETWORK,
    AcarsNetwork,
    all_tap_hosts,
    parse_network,
    profile_for,
)
from acars_bridge.tap.tcp_owner import process_matches


def test_default_is_hoppie():
    assert DEFAULT_NETWORK is AcarsNetwork.HOPPIE
    assert parse_network(None) is AcarsNetwork.HOPPIE
    assert parse_network("") is AcarsNetwork.HOPPIE
    assert parse_network("nope") is AcarsNetwork.HOPPIE


def test_sayintentions_profile_coexists_with_companion_app():
    profile = profile_for(AcarsNetwork.SAYINTENTIONS)
    assert profile.primary_host == "acars.sayintentions.ai"
    assert profile.tap_hosts == ("acars.sayintentions.ai",)
    assert profile.connect_url.endswith("/acars/system/connect.html")
    assert profile.hosts_redirect is False
    assert profile.divert_process_allowlist
    assert any("flightsimulator" in s for s in profile.divert_process_allowlist)
    assert any("sayintentions" in s for s in profile.divert_process_denylist)


def test_hoppie_profile_coexists_with_website():
    profile = profile_for("hoppie")
    assert profile.primary_host == "www.hoppie.nl"
    assert "www.hoppie.nl" in profile.tap_hosts
    assert "hoppie.nl" in profile.tap_hosts
    assert profile.hosts_redirect is False
    assert profile.divert_process_allowlist
    assert any("flightsimulator" in s for s in profile.divert_process_allowlist)


def test_all_tap_hosts_covers_both_networks():
    hosts = all_tap_hosts()
    assert "www.hoppie.nl" in hosts
    assert "acars.sayintentions.ai" in hosts
    assert "gfo.pmdg.com" in hosts
    assert len(hosts) == len(set(hosts))


def test_pmdg_gfo_profile():
    from acars_bridge.network import WireFormat

    profile = profile_for(AcarsNetwork.PMDG_GFO)
    assert profile.primary_host == "gfo.pmdg.com"
    assert profile.wire_format is WireFormat.GFO
    assert profile.connect_path.startswith("/api/datalink/")
    assert profile.hosts_redirect is False
    assert any("flightsimulator" in s for s in profile.divert_process_allowlist)


def test_process_matches():
    assert process_matches("FlightSimulator.exe", ("flightsimulator",))
    assert process_matches("SayIntentionsAI.exe", ("sayintentions",))
    assert not process_matches("notepad.exe", ("flightsimulator", "sayintentions"))
    assert not process_matches("FlightSimulator.exe", ())
