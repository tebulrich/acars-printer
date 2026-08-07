from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from acars_bridge.hoppie.types import HoppieMessage, MessageType
from acars_bridge.services.sterile import SterileGate, SterileThresholds, compute_sterile
from acars_bridge.simbrief.client import SimBriefClient, SimBriefError
from acars_bridge.simbrief.loadsheet import build_final_values, build_preliminary_values
from acars_bridge.simbrief.models import SimBriefFlightPlan, is_eligible_for_autoprint
from acars_bridge.simbrief.tickets import (
    render_flight_plan_ticket,
    render_loadsheet_ticket,
    render_takeoff_data_ticket,
)
from acars_bridge.simbrief.watcher import SimBriefWatcher, WatcherConfig, WatcherPhase
from acars_bridge.simconnect.monitor import SimSnapshot

FIXTURE = Path(__file__).parent / "fixtures" / "simbrief" / "sample_ofp.json"


@pytest.fixture
def sample_plan() -> SimBriefFlightPlan:
    root = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return SimBriefFlightPlan.from_json(root)


def test_parse_ofp_fields(sample_plan: SimBriefFlightPlan) -> None:
    assert sample_plan.ofp_id == "OFP-1001"
    assert sample_plan.callsign == "DLH4MC"
    assert sample_plan.origin_icao == "EDDF"
    assert sample_plan.dest_icao == "EDDM"
    assert sample_plan.alternate_icao == "EDDN"
    assert "CINDY8S" in sample_plan.route
    assert sample_plan.cruise_altitude == "FL350"
    assert sample_plan.sched_out_utc is not None
    assert sample_plan.origin_runway == "25C"
    assert sample_plan.dest_runway == "26L"
    assert sample_plan.cost_index == "30"
    assert sample_plan.trip_fuel == "4500"
    assert sample_plan.est_ldw == "59500"


def test_eligibility_future_and_stale(sample_plan: SimBriefFlightPlan) -> None:
    now = sample_plan.sched_out_utc - timedelta(hours=2)
    assert is_eligible_for_autoprint(sample_plan, now=now, last_ofp_id=None)
    assert not is_eligible_for_autoprint(
        sample_plan, now=now, last_ofp_id=sample_plan.ofp_id
    )
    past = sample_plan.sched_out_utc + timedelta(hours=3)
    assert not is_eligible_for_autoprint(sample_plan, now=past, last_ofp_id=None)
    near = sample_plan.sched_out_utc + timedelta(minutes=30)
    assert is_eligible_for_autoprint(sample_plan, now=near, last_ofp_id=None)


def test_manual_unlock_forgets_last_ofp(app_session, sample_plan: SimBriefFlightPlan) -> None:
    app_session.settings.set_simbrief_last_ofp_id(sample_plan.ofp_id)
    watcher = SimBriefWatcher(
        settings=app_session.settings,
        print_manager=app_session.print_manager,
        sterile=app_session.sterile,
    )
    watcher.unlock(reason="manual")
    assert app_session.settings.simbrief_last_ofp_id() is None
    watcher.settings.set_simbrief_last_ofp_id(sample_plan.ofp_id)
    watcher.unlock(reason="post-landing grace done")
    assert app_session.settings.simbrief_last_ofp_id() == sample_plan.ofp_id


def test_loadsheet_math_and_randomize(sample_plan: SimBriefFlightPlan) -> None:
    prelim = build_preliminary_values(sample_plan)
    assert prelim.pax_count == 150
    final = build_final_values(sample_plan, randomize=True, rng=__import__("random").Random(0))
    assert final.pax_delta is not None
    assert abs(final.pax_delta) <= 3


def test_tickets_keep_full_route(sample_plan: SimBriefFlightPlan) -> None:
    text = render_flight_plan_ticket(sample_plan, width=32)
    for token in sample_plan.route.split():
        assert token in text
    assert "ACARS START" in text
    assert "01JAN30" in text
    assert "DATE:" in text
    assert "STD:" in text
    assert "STA:" in text
    prelim = build_preliminary_values(sample_plan)
    sheet = render_loadsheet_ticket(sample_plan, "PRELIMINARY", prelim, width=32)
    assert "LOAD SHEET" in sheet
    assert "01JAN30" in sheet
    assert "STD:" in sheet
    takeoff = render_takeoff_data_ticket(sample_plan, width=32)
    assert "TAKEOFF DATA" in takeoff
    assert "DEP RWY:" in takeoff
    assert "25C" in takeoff
    assert "TRIP FUEL:" in takeoff
    assert "4500" in takeoff
    assert "01JAN30" in takeoff
    assert "STD:" in takeoff
    assert "PRELIMINARY" in sheet
    assert "ACARS START" in sheet
    assert "ACARS END" in sheet


def test_sterile_compute() -> None:
    assert compute_sterile(None) is False
    assert (
        compute_sterile(
            SimSnapshot(connected=True, on_ground=True, ground_velocity_kt=10, alt_agl_ft=0)
        )
        is False
    )
    assert (
        compute_sterile(
            SimSnapshot(connected=True, on_ground=True, ground_velocity_kt=80, alt_agl_ft=0)
        )
        is True
    )
    assert (
        compute_sterile(
            SimSnapshot(connected=True, on_ground=False, ground_velocity_kt=200, alt_agl_ft=800)
        )
        is True
    )
    assert (
        compute_sterile(
            SimSnapshot(connected=True, on_ground=False, ground_velocity_kt=200, alt_agl_ft=2000)
        )
        is False
    )
    # Custom AGL ceiling (e.g. sterile until 5000 ft)
    high = SterileThresholds(agl_ft=5000.0)
    assert (
        compute_sterile(
            SimSnapshot(connected=True, on_ground=False, ground_velocity_kt=200, alt_agl_ft=3000),
            thresholds=high,
        )
        is True
    )
    assert (
        compute_sterile(
            SimSnapshot(connected=True, on_ground=False, ground_velocity_kt=200, alt_agl_ft=5500),
            thresholds=high,
        )
        is False
    )


def test_sterile_defers_and_flushes() -> None:
    gate = SterileGate()
    ran: list[str] = []
    gate.update_from_snapshot(
        SimSnapshot(connected=True, on_ground=True, ground_velocity_kt=80, alt_agl_ft=0)
    )
    assert gate.is_sterile
    deferred = gate.run_or_defer_acars(lambda: ran.append("acars"))
    assert deferred is True
    gate.update_from_snapshot(
        SimSnapshot(connected=True, on_ground=True, ground_velocity_kt=10, alt_agl_ft=0)
    )
    assert ran == ["acars"]


def test_power_gate_defers_until_battery_on() -> None:
    gate = SterileGate(require_powered=True, flush_stagger_seconds=0)
    ran: list[str] = []
    gate.update_from_snapshot(
        SimSnapshot(
            connected=True,
            on_ground=True,
            ground_velocity_kt=0,
            alt_agl_ft=0,
            battery_on=False,
        )
    )
    assert gate.is_unpowered
    assert gate.is_blocking
    assert gate.run_or_defer_acars(lambda: ran.append("acars")) is True
    assert ran == []
    # Disconnected must not hold forever.
    gate.update_from_snapshot(None)
    assert not gate.is_blocking
    assert ran == ["acars"]

    ran.clear()
    gate.update_from_snapshot(
        SimSnapshot(
            connected=True,
            on_ground=True,
            ground_velocity_kt=0,
            alt_agl_ft=0,
            battery_on=False,
        )
    )
    assert gate.run_or_defer_simbrief(lambda: ran.append("sb")) is True
    gate.update_from_snapshot(
        SimSnapshot(
            connected=True,
            on_ground=True,
            ground_velocity_kt=0,
            alt_agl_ft=0,
            battery_on=True,
        )
    )
    assert ran == ["sb"]


def test_power_gate_off_ignores_battery() -> None:
    gate = SterileGate(require_powered=False)
    gate.update_from_snapshot(
        SimSnapshot(
            connected=True,
            on_ground=True,
            ground_velocity_kt=0,
            alt_agl_ft=0,
            battery_on=False,
        )
    )
    assert not gate.is_blocking
    ran: list[str] = []
    assert gate.run_or_defer_acars(lambda: ran.append("ok")) is False
    assert ran == ["ok"]


def test_acars_ingestion_defers_when_sterile(app_session) -> None:
    gate = app_session.sterile
    gate.update_from_snapshot(
        SimSnapshot(connected=True, on_ground=False, ground_velocity_kt=180, alt_agl_ft=500)
    )
    msg = HoppieMessage(
        callsign="SWR14",
        sender="EDDF_TWR",
        recipient="SWR14",
        message_type=MessageType.TELEX,
        raw_payload="hello",
        normalized_body="HELLO FROM TWR",
    )
    stats = app_session.ingestion.ingest([msg])
    assert stats["deferred"] == 1
    assert app_session.db.conn.execute("SELECT COUNT(*) AS c FROM print_jobs").fetchone()["c"] == 0
    gate.update_from_snapshot(
        SimSnapshot(connected=True, on_ground=False, ground_velocity_kt=180, alt_agl_ft=3000)
    )
    assert app_session.db.conn.execute("SELECT COUNT(*) AS c FROM print_jobs").fetchone()["c"] == 1


def test_simbrief_client_mock(sample_plan: SimBriefFlightPlan) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        assert "json=1" in str(request.url)
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    client = SimBriefClient(transport=transport)
    plan = client.fetch_latest("12345")
    assert plan.ofp_id == sample_plan.ofp_id

    with pytest.raises(SimBriefError):
        client.fetch_latest("")


def test_watcher_lock_final_missed_and_landing(app_session, sample_plan: SimBriefFlightPlan) -> None:
    # Make SOBT relative to "now" used by watcher clock.
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    plan = SimBriefFlightPlan(
        **{
            **{f.name: getattr(sample_plan, f.name) for f in sample_plan.__dataclass_fields__.values()},  # type: ignore[attr-defined]
            "ofp_id": "OFP-LIVE",
            "sched_out_utc": now + timedelta(minutes=30),
        }
    )
    # Rebuild frozen dataclass properly
    plan = SimBriefFlightPlan(
        ofp_id="OFP-LIVE",
        callsign=sample_plan.callsign,
        airline_icao=sample_plan.airline_icao,
        flight_number=sample_plan.flight_number,
        aircraft_icao=sample_plan.aircraft_icao,
        aircraft_name=sample_plan.aircraft_name,
        aircraft_reg=sample_plan.aircraft_reg,
        origin_icao=sample_plan.origin_icao,
        origin_iata=sample_plan.origin_iata,
        origin_name=sample_plan.origin_name,
        dest_icao=sample_plan.dest_icao,
        dest_iata=sample_plan.dest_iata,
        dest_name=sample_plan.dest_name,
        alternate_icao=sample_plan.alternate_icao,
        alternate_name=sample_plan.alternate_name,
        route=sample_plan.route,
        cruise_altitude=sample_plan.cruise_altitude,
        distance_nm=sample_plan.distance_nm,
        flight_time_formatted=sample_plan.flight_time_formatted,
        units=sample_plan.units,
        block_fuel=sample_plan.block_fuel,
        taxi_fuel=sample_plan.taxi_fuel,
        takeoff_fuel=sample_plan.takeoff_fuel,
        zfw=sample_plan.zfw,
        tow=sample_plan.tow,
        max_zfw=sample_plan.max_zfw,
        max_tow=sample_plan.max_tow,
        pax_count=sample_plan.pax_count,
        pax_weight_avg=sample_plan.pax_weight_avg,
        cargo_weight=sample_plan.cargo_weight,
        sched_out_zulu=sample_plan.sched_out_zulu,
        sched_in_zulu=sample_plan.sched_in_zulu,
        sched_out_utc=now + timedelta(minutes=30),
    )

    class FakeClient:
        def fetch_latest(self, user: str) -> SimBriefFlightPlan:
            return plan

    mono = {"t": 1000.0}

    def now_fn() -> float:
        return mono["t"]

    def clock_fn(_snap: SimSnapshot | None) -> datetime:
        return now

    app_session.settings.set_simbrief_enabled(True)
    app_session.settings.set_simbrief_user("pilot")
    watcher = SimBriefWatcher(
        settings=app_session.settings,
        print_manager=app_session.print_manager,
        sterile=app_session.sterile,
        client=FakeClient(),  # type: ignore[arg-type]
        config=WatcherConfig(
            poll_seconds=60,
            airborne_debounce_seconds=2,
            landing_debounce_seconds=3,
            post_landing_grace_seconds=5,
        ),
        _now_fn=now_fn,
        _clock_fn=clock_fn,
    )
    app_session.simbrief_watcher = watcher

    ground = SimSnapshot(connected=True, on_ground=True, ground_velocity_kt=0, alt_agl_ft=0)
    watcher.tick(ground)
    assert watcher.state.phase == WatcherPhase.LOCKED
    jobs = app_session.db.conn.execute("SELECT COUNT(*) AS c FROM print_jobs").fetchone()["c"]
    assert jobs == 3  # FP + takeoff data + prelim

    # Taxi GS — need sustained roll (10s) before final
    taxi = SimSnapshot(connected=True, on_ground=True, ground_velocity_kt=8, alt_agl_ft=0)
    watcher.tick(taxi)
    assert watcher.state.phase == WatcherPhase.LOCKED
    assert not watcher.state.final_printed

    mono["t"] += 9
    watcher.tick(taxi)
    assert not watcher.state.final_printed

    mono["t"] += 2
    watcher.tick(taxi)
    assert watcher.state.phase == WatcherPhase.FINAL_PRINTED
    assert watcher.state.final_printed

    # Airborne (needs sustained debounce across ticks)
    air = SimSnapshot(connected=True, on_ground=False, ground_velocity_kt=160, alt_agl_ft=500)
    mono["t"] += 1
    watcher.tick(air)
    mono["t"] += 3
    watcher.tick(air)
    assert watcher.state.phase == WatcherPhase.AIRBORNE

    # Land
    land = SimSnapshot(connected=True, on_ground=True, ground_velocity_kt=20, alt_agl_ft=0)
    mono["t"] += 1
    watcher.tick(land)
    mono["t"] += 4
    watcher.tick(land)
    assert watcher.state.phase == WatcherPhase.POST_LANDING

    mono["t"] += 6
    watcher.tick(land)
    assert watcher.state.phase == WatcherPhase.POLLING


def test_watcher_final_on_door_close(app_session, sample_plan: SimBriefFlightPlan) -> None:
    from dataclasses import replace

    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    plan = replace(
        sample_plan,
        ofp_id="OFP-DOORS",
        sched_out_utc=now + timedelta(hours=2),
    )

    class FakeClient:
        def fetch_latest(self, user: str) -> SimBriefFlightPlan:
            return plan

    mono = {"t": 1000.0}
    app_session.settings.set_simbrief_enabled(True)
    app_session.settings.set_simbrief_user("pilot")
    watcher = SimBriefWatcher(
        settings=app_session.settings,
        print_manager=app_session.print_manager,
        sterile=app_session.sterile,
        client=FakeClient(),  # type: ignore[arg-type]
        config=WatcherConfig(door_close_seconds=2.0, taxi_roll_seconds=30.0),
        _now_fn=lambda: mono["t"],
        _clock_fn=lambda _s: now,
    )

    closed = SimSnapshot(
        connected=True, on_ground=True, ground_velocity_kt=0, main_door_open=False
    )
    watcher.tick(closed)
    assert watcher.state.phase == WatcherPhase.LOCKED
    assert not watcher.state.final_printed
    # Always closed so far — door trigger must not arm.
    assert not watcher.state.doors_seen_open

    open_door = SimSnapshot(
        connected=True, on_ground=True, ground_velocity_kt=0, main_door_open=True
    )
    watcher.tick(open_door)
    assert watcher.state.doors_seen_open
    assert not watcher.state.final_printed

    # T−5 would have fired if we ignored open doors — clock still far out.
    mono["t"] += 1
    watcher.tick(closed)
    assert not watcher.state.final_printed
    mono["t"] += 2
    watcher.tick(closed)
    assert watcher.state.final_printed
    assert watcher.state.phase == WatcherPhase.FINAL_PRINTED


def test_watcher_final_t5_when_doors_always_closed(
    app_session, sample_plan: SimBriefFlightPlan
) -> None:
    from dataclasses import replace

    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    plan = replace(
        sample_plan,
        ofp_id="OFP-T5",
        sched_out_utc=now + timedelta(minutes=4),
    )

    class FakeClient:
        def fetch_latest(self, user: str) -> SimBriefFlightPlan:
            return plan

    app_session.settings.set_simbrief_enabled(True)
    app_session.settings.set_simbrief_user("pilot")
    watcher = SimBriefWatcher(
        settings=app_session.settings,
        print_manager=app_session.print_manager,
        sterile=app_session.sterile,
        client=FakeClient(),  # type: ignore[arg-type]
        config=WatcherConfig(taxi_roll_seconds=60.0),
        _now_fn=lambda: 0.0,
        _clock_fn=lambda _s: now,
    )

    closed = SimSnapshot(
        connected=True, on_ground=True, ground_velocity_kt=0, main_door_open=False
    )
    watcher.tick(closed)
    assert watcher.state.phase == WatcherPhase.LOCKED
    watcher.tick(closed)
    assert watcher.state.phase == WatcherPhase.FINAL_PRINTED
    assert watcher.state.final_printed
    assert not watcher.state.doors_seen_open


def test_fenix_skips_loadsheets(app_session, sample_plan: SimBriefFlightPlan) -> None:
    from dataclasses import replace

    from acars_bridge.simbrief.models import is_fenix_aircraft

    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    plan = replace(
        sample_plan,
        ofp_id="OFP-FENIX",
        aircraft_name="FENIX A320",
        aircraft_icao="A320",
        sched_out_utc=now + timedelta(minutes=4),
    )
    assert is_fenix_aircraft(plan)

    class FakeClient:
        def fetch_latest(self, user: str) -> SimBriefFlightPlan:
            return plan

    app_session.settings.set_simbrief_enabled(True)
    app_session.settings.set_simbrief_user("pilot")
    watcher = SimBriefWatcher(
        settings=app_session.settings,
        print_manager=app_session.print_manager,
        sterile=app_session.sterile,
        client=FakeClient(),  # type: ignore[arg-type]
        _now_fn=lambda: 0.0,
        _clock_fn=lambda _s: now,
    )
    snap = SimSnapshot(
        connected=True, on_ground=True, ground_velocity_kt=0, main_door_open=False
    )
    watcher.tick(snap)
    assert watcher.state.final_printed
    assert watcher.state.phase == WatcherPhase.FINAL_PRINTED
    types = [
        r["message_type"]
        for r in app_session.db.conn.execute(
            "SELECT message_type FROM messages ORDER BY id"
        ).fetchall()
    ]
    assert "flight_plan" in types
    assert "takeoff_data" in types
    assert "loadsheet_prelim" not in types
    assert "loadsheet_final" not in types
    # T−5 must not print a final either.
    watcher.tick(snap)
    types2 = [
        r["message_type"]
        for r in app_session.db.conn.execute(
            "SELECT message_type FROM messages ORDER BY id"
        ).fetchall()
    ]
    assert types2.count("loadsheet_final") == 0


def test_print_ticket_no_acars_wrapper(app_session, sample_plan: SimBriefFlightPlan) -> None:
    body = render_flight_plan_ticket(sample_plan, width=32)
    result = app_session.print_manager.print_ticket(
        body,
        app_session.settings.as_printer_settings(),
        callsign=sample_plan.callsign,
        ticket_type="flight_plan",
    )
    assert result == "printed"
    row = app_session.db.conn.execute(
        "SELECT message_type, normalized_body FROM messages ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["message_type"] == "flight_plan"
    assert "ACARS BEGIN" not in row["normalized_body"]
    assert "ACARS START" in row["normalized_body"]
    for token in sample_plan.route.split():
        assert token in row["normalized_body"]


def test_watcher_missed_final_after_landing(app_session, sample_plan: SimBriefFlightPlan) -> None:
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    plan = SimBriefFlightPlan(
        ofp_id="OFP-MISS",
        callsign=sample_plan.callsign,
        airline_icao=sample_plan.airline_icao,
        flight_number=sample_plan.flight_number,
        aircraft_icao=sample_plan.aircraft_icao,
        aircraft_name=sample_plan.aircraft_name,
        aircraft_reg=sample_plan.aircraft_reg,
        origin_icao=sample_plan.origin_icao,
        origin_iata=sample_plan.origin_iata,
        origin_name=sample_plan.origin_name,
        dest_icao=sample_plan.dest_icao,
        dest_iata=sample_plan.dest_iata,
        dest_name=sample_plan.dest_name,
        alternate_icao=sample_plan.alternate_icao,
        alternate_name=sample_plan.alternate_name,
        route=sample_plan.route,
        cruise_altitude=sample_plan.cruise_altitude,
        distance_nm=sample_plan.distance_nm,
        flight_time_formatted=sample_plan.flight_time_formatted,
        units=sample_plan.units,
        block_fuel=sample_plan.block_fuel,
        taxi_fuel=sample_plan.taxi_fuel,
        takeoff_fuel=sample_plan.takeoff_fuel,
        zfw=sample_plan.zfw,
        tow=sample_plan.tow,
        max_zfw=sample_plan.max_zfw,
        max_tow=sample_plan.max_tow,
        pax_count=sample_plan.pax_count,
        pax_weight_avg=sample_plan.pax_weight_avg,
        cargo_weight=sample_plan.cargo_weight,
        sched_out_zulu=sample_plan.sched_out_zulu,
        sched_in_zulu=sample_plan.sched_in_zulu,
        sched_out_utc=now + timedelta(hours=2),
    )

    class FakeClient:
        def fetch_latest(self, user: str) -> SimBriefFlightPlan:
            return plan

    mono = {"t": 0.0}
    app_session.settings.set_simbrief_enabled(True)
    app_session.settings.set_simbrief_user("pilot")
    watcher = SimBriefWatcher(
        settings=app_session.settings,
        print_manager=app_session.print_manager,
        sterile=app_session.sterile,
        client=FakeClient(),  # type: ignore[arg-type]
        config=WatcherConfig(
            airborne_debounce_seconds=1,
            landing_debounce_seconds=1,
            post_landing_grace_seconds=100,
        ),
        _now_fn=lambda: mono["t"],
        _clock_fn=lambda _s: now,
    )

    watcher.tick(SimSnapshot(connected=True, on_ground=True, ground_velocity_kt=0))
    assert watcher.state.phase == WatcherPhase.LOCKED
    before = app_session.db.conn.execute("SELECT COUNT(*) AS c FROM print_jobs").fetchone()["c"]

    # Jump to airborne without taxi final (debounce across ticks)
    mono["t"] = 5
    air = SimSnapshot(connected=True, on_ground=False, ground_velocity_kt=180, alt_agl_ft=400)
    watcher.tick(air)
    mono["t"] = 7
    watcher.tick(air)
    assert watcher.state.phase == WatcherPhase.AIRBORNE
    assert watcher.state.missed_final_pending is True

    # Still sterile low AGL — no missed final yet
    mid = app_session.db.conn.execute("SELECT COUNT(*) AS c FROM print_jobs").fetchone()["c"]
    assert mid == before

    # Land and clear sterile
    mono["t"] = 10
    land = SimSnapshot(connected=True, on_ground=True, ground_velocity_kt=10, alt_agl_ft=0)
    watcher.tick(land)
    mono["t"] = 12
    watcher.tick(land)
    assert watcher.state.phase == WatcherPhase.POST_LANDING
    after = app_session.db.conn.execute("SELECT COUNT(*) AS c FROM print_jobs").fetchone()["c"]
    assert after == before + 1
    assert watcher.state.missed_final_pending is False


def test_sterile_queue_caps_and_drops() -> None:
    gate = SterileGate(max_queue=2, flush_stagger_seconds=0)
    gate.update_from_snapshot(
        SimSnapshot(connected=True, on_ground=True, ground_velocity_kt=80, alt_agl_ft=0)
    )
    ran: list[int] = []
    for i in range(4):
        gate.run_or_defer_acars(lambda i=i: ran.append(i))
    assert gate.queue_sizes() == (2, 0)
    assert gate.dropped_count == 2
    gate.update_from_snapshot(
        SimSnapshot(connected=True, on_ground=True, ground_velocity_kt=0, alt_agl_ft=0)
    )
    assert ran == [2, 3]


def test_sterile_independent_of_simbrief_enabled(app_session) -> None:
    """Sterile must work for ACARS even when SimBrief is off (UI drives the gate)."""
    app_session.settings.set_simbrief_enabled(False)
    gate = app_session.sterile
    gate.update_from_snapshot(
        SimSnapshot(connected=True, on_ground=False, ground_velocity_kt=180, alt_agl_ft=400)
    )
    assert gate.is_sterile
    msg = HoppieMessage(
        callsign="SWR14",
        sender="EDDF_TWR",
        recipient="SWR14",
        message_type=MessageType.TELEX,
        raw_payload="hello",
        normalized_body="STERILE TEST",
    )
    stats = app_session.ingestion.ingest([msg])
    assert stats["deferred"] == 1


def test_watcher_persists_and_restores_plan(app_session, sample_plan: SimBriefFlightPlan) -> None:
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    plan = SimBriefFlightPlan(
        ofp_id="OFP-RESTORE",
        callsign=sample_plan.callsign,
        airline_icao=sample_plan.airline_icao,
        flight_number=sample_plan.flight_number,
        aircraft_icao=sample_plan.aircraft_icao,
        aircraft_name=sample_plan.aircraft_name,
        aircraft_reg=sample_plan.aircraft_reg,
        origin_icao=sample_plan.origin_icao,
        origin_iata=sample_plan.origin_iata,
        origin_name=sample_plan.origin_name,
        dest_icao=sample_plan.dest_icao,
        dest_iata=sample_plan.dest_iata,
        dest_name=sample_plan.dest_name,
        alternate_icao=sample_plan.alternate_icao,
        alternate_name=sample_plan.alternate_name,
        route=sample_plan.route,
        cruise_altitude=sample_plan.cruise_altitude,
        distance_nm=sample_plan.distance_nm,
        flight_time_formatted=sample_plan.flight_time_formatted,
        units=sample_plan.units,
        block_fuel=sample_plan.block_fuel,
        taxi_fuel=sample_plan.taxi_fuel,
        takeoff_fuel=sample_plan.takeoff_fuel,
        zfw=sample_plan.zfw,
        tow=sample_plan.tow,
        max_zfw=sample_plan.max_zfw,
        max_tow=sample_plan.max_tow,
        pax_count=sample_plan.pax_count,
        pax_weight_avg=sample_plan.pax_weight_avg,
        cargo_weight=sample_plan.cargo_weight,
        sched_out_zulu=sample_plan.sched_out_zulu,
        sched_in_zulu=sample_plan.sched_in_zulu,
        sched_out_utc=now + timedelta(hours=1),
    )

    class FakeClient:
        def fetch_latest(self, user: str) -> SimBriefFlightPlan:
            return plan

    app_session.settings.set_simbrief_enabled(True)
    app_session.settings.set_simbrief_user("pilot")
    watcher = SimBriefWatcher(
        settings=app_session.settings,
        print_manager=app_session.print_manager,
        sterile=app_session.sterile,
        client=FakeClient(),  # type: ignore[arg-type]
        config=WatcherConfig(poll_seconds=60),
        _now_fn=lambda: 100.0,
        _clock_fn=lambda _s: now,
    )
    watcher.tick(SimSnapshot(connected=True, on_ground=True, ground_velocity_kt=0))
    assert watcher.state.phase == WatcherPhase.LOCKED
    assert watcher.state.plan is not None
    raw = app_session.settings.simbrief_lock_state()
    assert "OFP-RESTORE" in raw
    assert '"plan"' in raw

    restored = SimBriefWatcher(
        settings=app_session.settings,
        print_manager=app_session.print_manager,
        sterile=app_session.sterile,
        client=FakeClient(),  # type: ignore[arg-type]
        config=WatcherConfig(poll_seconds=60),
        _now_fn=lambda: 100.0,
        _clock_fn=lambda _s: now,
    )
    assert restored.state.phase == WatcherPhase.LOCKED
    assert restored.state.ofp_id == "OFP-RESTORE"
    assert restored.state.plan is not None
    assert restored.state.plan.ofp_id == "OFP-RESTORE"
    assert restored.state.plan.route == plan.route


def test_plan_roundtrip_dict(sample_plan: SimBriefFlightPlan) -> None:
    again = SimBriefFlightPlan.from_dict(sample_plan.to_dict())
    assert again.ofp_id == sample_plan.ofp_id
    assert again.route == sample_plan.route
    assert again.sched_out_utc == sample_plan.sched_out_utc
