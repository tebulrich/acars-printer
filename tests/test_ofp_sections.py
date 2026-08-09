from __future__ import annotations

import json
from pathlib import Path

import pytest

from acars_bridge.simbrief.models import SimBriefFlightPlan
from acars_bridge.simbrief.watcher import SimBriefWatcher

FIXTURE = Path(__file__).parent / "fixtures" / "simbrief" / "sample_ofp.json"


@pytest.fixture
def sample_plan() -> SimBriefFlightPlan:
    root = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return SimBriefFlightPlan.from_json(root)


def test_ofp_tickets_default_all_enabled(app_session) -> None:
    assert app_session.settings.simbrief_ofp_tickets() == {
        "flight_plan",
        "takeoff_data",
        "loadsheet_prelim",
        "loadsheet_final",
    }


def test_set_ofp_tickets_roundtrip(app_session) -> None:
    app_session.settings.set_simbrief_ofp_tickets(["flight_plan", "takeoff_data"])
    assert app_session.settings.simbrief_ofp_tickets() == {
        "flight_plan",
        "takeoff_data",
    }


def test_bundle_respects_ofp_ticket_checklist(
    app_session, sample_plan: SimBriefFlightPlan
) -> None:
    app_session.settings.set_simbrief_ofp_tickets(["flight_plan"])
    watcher = SimBriefWatcher(
        settings=app_session.settings,
        print_manager=app_session.print_manager,
        sterile=app_session.sterile,
    )
    tickets = watcher._bundle_fp_prelim(sample_plan)
    assert [t[0] for t in tickets] == ["flight_plan"]


def test_bundle_fp_and_takeoff_only(app_session, sample_plan: SimBriefFlightPlan) -> None:
    app_session.settings.set_simbrief_ofp_tickets(
        ["flight_plan", "takeoff_data", "loadsheet_prelim"]
    )
    # Disable prelim
    app_session.settings.set_simbrief_ofp_tickets(["flight_plan", "takeoff_data"])
    watcher = SimBriefWatcher(
        settings=app_session.settings,
        print_manager=app_session.print_manager,
        sterile=app_session.sterile,
    )
    tickets = watcher._bundle_fp_prelim(sample_plan)
    assert [t[0] for t in tickets] == ["flight_plan", "takeoff_data"]


def test_final_skipped_when_loadsheet_final_disabled(
    app_session, sample_plan: SimBriefFlightPlan
) -> None:
    app_session.settings.set_simbrief_ofp_tickets(
        ["flight_plan", "takeoff_data", "loadsheet_prelim"]
    )
    watcher = SimBriefWatcher(
        settings=app_session.settings,
        print_manager=app_session.print_manager,
        sterile=app_session.sterile,
    )
    watcher.state.plan = sample_plan
    watcher.state.final_values = None
    watcher._print_final(sample_plan, reason="test")
    printer = app_session.print_manager._printer
    assert printer.printed == []
