from __future__ import annotations

from acars_bridge.network import AcarsNetwork
from acars_bridge.tap.divert import HoppieForceRedirect


def test_divert_accepts_multi_ip():
    divert = HoppieForceRedirect(["1.2.3.4", "5.6.7.8", "1.2.3.4"])
    assert divert.upstream_ips == frozenset({"1.2.3.4", "5.6.7.8"})


def test_divert_rejects_empty():
    try:
        HoppieForceRedirect([])
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_divert_allowlist_passthrough_when_owner_unknown():
    divert = HoppieForceRedirect(
        "1.2.3.4",
        process_allowlist=("flightsimulator",),
        process_denylist=("sayintentions",),
    )
    assert divert._owners is not None
    # No matching TCP owner in the test process table → do not divert.
    assert divert._should_divert_flow("10.0.0.2", 55555, "1.2.3.4", 443) is False


def test_settings_network_default_and_switch(app_session):
    settings = app_session.settings
    assert settings.acars_network() is AcarsNetwork.HOPPIE
    assert settings.hoppie_url().startswith("https://www.hoppie.nl/")

    settings.set_acars_network(AcarsNetwork.SAYINTENTIONS)
    assert settings.acars_network() is AcarsNetwork.SAYINTENTIONS
    assert settings.network_profile().primary_host == "acars.sayintentions.ai"
    assert "sayintentions.ai" in settings.hoppie_url()
    assert settings.network_profile().hosts_redirect is False

    settings.set_acars_network("bogus")
    assert settings.acars_network() is AcarsNetwork.HOPPIE
