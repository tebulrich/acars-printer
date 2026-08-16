from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from acars_bridge.models.settings import SettingsStore
from acars_bridge.services.print_manager import PrintManager
from acars_bridge.services.sterile import SterileGate
from acars_bridge.simbrief.client import SimBriefClient, SimBriefError
from acars_bridge.simbrief.loadsheet import (
    LoadsheetValues,
    build_final_values,
    build_preliminary_values,
)
from acars_bridge.simbrief.models import (
    SimBriefFlightPlan,
    is_eligible_for_autoprint,
    is_fenix_aircraft,
)
from acars_bridge.simbrief.tickets import (
    render_flight_plan_ticket,
    render_loadsheet_ticket,
    render_takeoff_data_ticket,
)
from acars_bridge.simconnect.monitor import SimSnapshot

log = logging.getLogger(__name__)

TICKET_GAP_SECONDS = 0.35


class WatcherPhase(StrEnum):
    POLLING = "polling"
    LOCKED = "locked"
    FINAL_PRINTED = "final_printed"
    AIRBORNE = "airborne"
    POST_LANDING = "post_landing"


@dataclass
class WatcherState:
    phase: WatcherPhase = WatcherPhase.POLLING
    ofp_id: str | None = None
    locked_at: float | None = None
    final_printed: bool = False
    lock_printed: bool = False
    motion_seen: bool = False
    missed_final_pending: bool = False
    airborne_since: float | None = None
    on_ground_since: float | None = None
    post_landing_since: float | None = None
    rolling_since: float | None = None
    doors_seen_open: bool = False
    doors_closed_since: float | None = None
    status: str = "idle"
    plan: SimBriefFlightPlan | None = None
    final_values: LoadsheetValues | None = None
    next_poll_at: float = 0.0
    backoff_seconds: float = 0.0


@dataclass
class WatcherConfig:
    poll_seconds: float = 60.0
    final_before_offblock_seconds: float = 5 * 60.0
    taxi_gs_min_kt: float = 3.0
    taxi_gs_max_kt: float = 40.0
    # Sustained ground roll before auto-printing the final loadsheet.
    taxi_roll_seconds: float = 10.0
    # After doors were seen open, print final once they stay closed this long.
    door_close_seconds: float = 2.0
    airborne_debounce_seconds: float = 15.0
    landing_debounce_seconds: float = 60.0
    post_landing_grace_seconds: float = 600.0
    max_lock_seconds: float = 8 * 3600.0
    sobt_late_grace: timedelta = timedelta(minutes=60)
    min_backoff_seconds: float = 60.0
    max_backoff_seconds: float = 600.0


PrintBundle = list[tuple[str, str]]  # (ticket_type, body)


def default_clock(snapshot: SimSnapshot | None) -> datetime:
    """Prefer sim Zulu calendar when connected; else wall UTC."""
    if (
        snapshot is not None
        and snapshot.connected
        and snapshot.zulu_year
        and snapshot.zulu_month
        and snapshot.zulu_day
        and snapshot.zulu_seconds is not None
    ):
        seconds = int(snapshot.zulu_seconds)
        hour, rem = divmod(seconds, 3600)
        minute, sec = divmod(rem, 60)
        try:
            return datetime(
                int(snapshot.zulu_year),
                int(snapshot.zulu_month),
                int(snapshot.zulu_day),
                int(hour),
                int(minute),
                int(sec),
                tzinfo=UTC,
            )
        except ValueError:
            pass
    return datetime.now(UTC)


@dataclass
class SimBriefWatcher:
    """Poll → lock → final → airborne → post-landing state machine."""

    settings: SettingsStore
    print_manager: PrintManager
    sterile: SterileGate
    client: SimBriefClient = field(default_factory=SimBriefClient)
    config: WatcherConfig = field(default_factory=WatcherConfig)
    state: WatcherState = field(default_factory=WatcherState)
    _now_fn: Callable[[], float] = field(default=time.time)
    _clock_fn: Callable[[SimSnapshot | None], datetime] = field(default=default_clock)

    def __post_init__(self) -> None:
        self._restore()

    def status_text(self) -> str:
        """Full status line (tooltips / debug). Prefer ``chip_text`` for the header."""
        return self.state.status

    def chip_text(self) -> str:
        """Short header label — phase or callsign only, no vendor jargon."""
        if not self.settings.simbrief_enabled():
            return "off"
        if not self.settings.simbrief_user():
            return "setup"

        cs = (self.state.plan.callsign if self.state.plan else "").strip()
        phase = self.state.phase
        st = (self.state.status or "").lower()

        if phase == WatcherPhase.POLLING:
            if "error" in st:
                return "error"
            if st.startswith("waiting"):
                return "waiting"
            return "idle"
        if phase == WatcherPhase.LOCKED:
            return cs or "locked"
        if phase == WatcherPhase.FINAL_PRINTED:
            return cs or "ready"
        if phase == WatcherPhase.AIRBORNE:
            return cs or "airborne"
        if phase == WatcherPhase.POST_LANDING:
            return "landing"
        return cs or phase.value

    def status_detail(self) -> str:
        """Tooltip body: human status + aircraft-specific notes."""
        raw = (self.state.status or "").strip()
        # Older builds wrote "fenix · no loadsheet" into the status string.
        cleaned = (
            raw.replace(" · fenix · no loadsheet", "")
            .replace("fenix · no loadsheet · ", "")
            .replace(" · fenix · ", " · ")
            .replace("print now · fenix · ", "print now · ")
            .strip(" ·")
        )
        lines: list[str] = []
        if cleaned:
            lines.append(cleaned)
        plan = self.state.plan
        if plan is not None:
            route = f"{plan.origin_icao}-{plan.dest_icao}".strip("-")
            if route and route not in cleaned:
                lines.append(f"{plan.callsign} {route}".strip())
            if is_fenix_aircraft(plan):
                lines.append(
                    "Fenix OFP: flight plan and takeoff print here; "
                    "loadsheet stays on the aircraft EFB."
                )
        return "\n".join(lines) if lines else "SimBrief idle"

    def tick(self, snapshot: SimSnapshot | None = None, *, do_network: bool = True) -> None:
        """Advance local state. When ``do_network`` is False, skip SimBrief HTTP."""
        self.tick_local(snapshot)
        if do_network:
            self.poll_network_if_due()

    def tick_local(self, snapshot: SimSnapshot | None = None) -> None:
        """SimConnect-driven phase + final triggers (no HTTP). Safe on the UI thread."""
        if not self.settings.simbrief_enabled():
            self.state.status = "disabled"
            # Still advance airborne/landing if a lock survived from earlier.
            if self.state.phase != WatcherPhase.POLLING:
                self._update_flight_phase(snapshot, self._now_fn())
            return

        user = self.settings.simbrief_user()
        if not user:
            self.state.status = "set SimBrief username/ID"
            if self.state.phase != WatcherPhase.POLLING:
                self._update_flight_phase(snapshot, self._now_fn())
            return

        now_mono = self._now_fn()
        now_utc = self._clock_fn(snapshot)

        if (
            self.state.phase
            in {
                WatcherPhase.LOCKED,
                WatcherPhase.FINAL_PRINTED,
                WatcherPhase.AIRBORNE,
            }
            and self.state.locked_at is not None
            and (now_mono - self.state.locked_at) >= self.config.max_lock_seconds
        ):
            self.unlock(reason="max lock elapsed")
            return

        self._update_flight_phase(snapshot, now_mono)

        if (
            self.state.phase == WatcherPhase.POST_LANDING
            and self.state.missed_final_pending
            and self.state.plan is not None
            and not is_fenix_aircraft(self.state.plan)
            and not self.sterile.is_sterile
        ):
            self._print_final(self.state.plan, reason="missed final after landing")
            self.state.missed_final_pending = False
            self.state.final_printed = True
            self._persist()

        if self.state.phase == WatcherPhase.LOCKED and self.state.plan is not None:
            # Fenix prints its own loadsheet — skip ours for already-locked OFPs too.
            if is_fenix_aircraft(self.state.plan) and not self.state.final_printed:
                self.state.final_printed = True
                self.state.missed_final_pending = False
                self.state.phase = WatcherPhase.FINAL_PRINTED
                plan = self.state.plan
                self.state.status = (
                    f"locked · {plan.callsign} {plan.origin_icao}-{plan.dest_icao}"
                )
                self._persist()
            elif self._should_print_final(snapshot, now_utc):
                self._print_final(self.state.plan, reason="final trigger")
                self.state.final_printed = True
                self.state.phase = WatcherPhase.FINAL_PRINTED
                self.state.status = f"final printed · {self.state.plan.callsign}"
                self._persist()

        self._refresh_status(snapshot)

    def needs_network_poll(self) -> bool:
        if not self.settings.simbrief_enabled() or not self.settings.simbrief_user():
            return False
        if self.state.phase == WatcherPhase.AIRBORNE:
            return False
        return self._now_fn() >= self.state.next_poll_at

    def poll_network_if_due(self) -> None:
        if not self.needs_network_poll():
            return
        user = self.settings.simbrief_user()
        if not user:
            return
        self._poll(user, self._clock_fn(None), self._now_fn())

    def print_now(self) -> str:
        user = self.settings.simbrief_user()
        if not user:
            raise SimBriefError("Enter your SimBrief username or pilot ID first.")
        plan = self.client.fetch_latest(user)
        self._lock_onto(plan, print_all_three=True, bypass_eligibility=True)
        return f"printed {plan.callsign} {plan.origin_icao}-{plan.dest_icao}"

    def unlock(self, *, reason: str = "manual") -> None:
        # Manual unlock means "start over" — allow the same OFP to lock again.
        # Automatic unlocks keep last_ofp_id so we don't immediately re-print.
        if reason == "manual":
            self.settings.set_simbrief_last_ofp_id(None)
            self.print_manager.reset_pairing_qr()
        self.state = WatcherState(
            phase=WatcherPhase.POLLING,
            status=f"unlocked ({reason})",
            next_poll_at=self._now_fn(),
        )
        self._persist()

    def _poll(self, user: str, now_utc: datetime, now_mono: float) -> None:
        try:
            plan = self.client.fetch_latest(user)
            self.state.backoff_seconds = 0.0
            self.state.next_poll_at = now_mono + self.config.poll_seconds
        except SimBriefError as exc:
            self.state.backoff_seconds = min(
                self.config.max_backoff_seconds,
                max(self.config.min_backoff_seconds, (self.state.backoff_seconds or 30.0) * 2),
            )
            self.state.next_poll_at = now_mono + self.state.backoff_seconds
            self.state.status = f"SimBrief error · retry in {int(self.state.backoff_seconds)}s"
            log.info("SimBrief poll failed: %s", exc)
            self._persist()
            return

        last_handled = self.settings.simbrief_last_ofp_id()

        if self.state.phase == WatcherPhase.POST_LANDING:
            if is_eligible_for_autoprint(
                plan,
                now=now_utc,
                last_ofp_id=last_handled,
                late_grace=self.config.sobt_late_grace,
            ):
                self.unlock(reason="new OFP during turnaround")
                self._lock_onto(plan, print_all_three=False, bypass_eligibility=False)
            else:
                # Remember ineligible so we don't thrash.
                if plan.ofp_id != last_handled and plan.sched_out_utc is not None:
                    if plan.sched_out_utc < (now_utc - self.config.sobt_late_grace):
                        self.settings.set_simbrief_last_ofp_id(plan.ofp_id)
            return

        if self.state.phase == WatcherPhase.POLLING:
            if is_eligible_for_autoprint(
                plan,
                now=now_utc,
                last_ofp_id=last_handled,
                late_grace=self.config.sobt_late_grace,
            ):
                self._lock_onto(plan, print_all_three=False, bypass_eligibility=False)
            else:
                if last_handled != plan.ofp_id:
                    # Remember stale/same so first start doesn't print yesterday.
                    self.settings.set_simbrief_last_ofp_id(plan.ofp_id)
                self.state.status = self._waiting_status(plan, now_utc)
            self._persist()
            return

        # Locked / final_printed: handle regen before motion+final.
        if self.state.ofp_id and plan.ofp_id != self.state.ofp_id:
            can_regen = (
                self.state.phase == WatcherPhase.LOCKED
                and not self.state.motion_seen
                and not self.state.final_printed
            )
            if can_regen:
                self._lock_onto(plan, print_all_three=False, bypass_eligibility=True)
            else:
                # New OFP after motion/final — stay locked until unlock cycle;
                # only switch if eligible after unlock. Remember for later.
                self.state.status = (
                    f"locked {self.state.plan.callsign if self.state.plan else ''} · "
                    f"new OFP pending"
                )
                self._persist()

    def _lock_onto(
        self,
        plan: SimBriefFlightPlan,
        *,
        print_all_three: bool,
        bypass_eligibility: bool,
    ) -> None:
        del bypass_eligibility  # caller decides
        skip_auto_print = (
            not print_all_three
            and self.state.lock_printed
            and bool(plan.ofp_id)
            and plan.ofp_id == self.state.ofp_id
        )
        if skip_auto_print:
            self.state.plan = plan
            self.state.ofp_id = plan.ofp_id
            self.state.status = (
                f"locked · {plan.callsign} {plan.origin_icao}-{plan.dest_icao}"
            )
            self._persist()
            return
        self.state.plan = plan
        self.state.ofp_id = plan.ofp_id
        self.state.phase = WatcherPhase.LOCKED
        self.state.locked_at = self._now_fn()
        self.state.final_printed = False
        self.state.motion_seen = False
        self.state.missed_final_pending = False
        self.state.airborne_since = None
        self.state.on_ground_since = None
        self.state.post_landing_since = None
        self.state.rolling_since = None
        self.state.doors_seen_open = False
        self.state.doors_closed_since = None
        self.state.final_values = build_final_values(plan)
        self.settings.set_simbrief_last_ofp_id(plan.ofp_id)

        if print_all_three:
            # Manual Print OFP: FP + takeoff + prelim only. Final prints once
            # at door-close / T−5 / taxi — including it here caused a duplicate.
            # Fenix: FP + takeoff only (aircraft prints its own loadsheet).
            self._print_bundle(self._bundle_fp_prelim(plan), label="print-now")
            if self._skips_final_loadsheet(plan):
                self.state.final_printed = True
                self.state.phase = WatcherPhase.FINAL_PRINTED
            else:
                self.state.final_printed = False
                self.state.phase = WatcherPhase.LOCKED
            self.state.lock_printed = True
            self.state.status = f"print now · {plan.callsign}"
        else:
            self._print_bundle(self._bundle_fp_prelim(plan), label="lock")
            self.state.lock_printed = True
            if self._skips_final_loadsheet(plan):
                self.state.final_printed = True
                self.state.phase = WatcherPhase.FINAL_PRINTED
            self.state.status = (
                f"locked · {plan.callsign} {plan.origin_icao}-{plan.dest_icao}"
            )
        self._persist()

    def _skips_final_loadsheet(self, plan: SimBriefFlightPlan) -> bool:
        if is_fenix_aircraft(plan):
            return True
        return not self.settings.simbrief_ofp_ticket_enabled("loadsheet_final")

    def _should_print_final(self, snapshot: SimSnapshot | None, now_utc: datetime) -> bool:
        if self.state.final_printed or self.state.plan is None:
            return False
        if self._skips_final_loadsheet(self.state.plan):
            return False
        if self.sterile.is_blocking:
            return False

        plan = self.state.plan
        now_mono = self._now_fn()
        door: bool | None = None

        if snapshot is not None and snapshot.connected and snapshot.on_ground:
            door = snapshot.main_door_open
            # Preferred: doors were open (boarding), then closed and stay closed.
            if door is True:
                self.state.doors_seen_open = True
                self.state.doors_closed_since = None
            elif door is False and self.state.doors_seen_open:
                if self.state.doors_closed_since is None:
                    self.state.doors_closed_since = now_mono
                elif (now_mono - self.state.doors_closed_since) >= self.config.door_close_seconds:
                    return True
            else:
                # Unknown / never opened — do not arm door trigger.
                self.state.doors_closed_since = None
        else:
            self.state.doors_closed_since = None

        # Still boarding — wait for close (missed-final covers never-closed).
        if door is True:
            self.state.rolling_since = None
            return False

        # Fallback when doors never opened / always closed / unknown: T−5 SOBT.
        if plan.sched_out_utc is not None:
            lead = timedelta(seconds=self.config.final_before_offblock_seconds)
            if now_utc >= (plan.sched_out_utc - lead):
                return True

        if snapshot is None or not snapshot.connected or not snapshot.on_ground:
            self.state.rolling_since = None
            return False

        # Fallback: sustained taxi roll on the ground (not airborne).
        gs = snapshot.ground_velocity_kt
        rolling = self.config.taxi_gs_min_kt < gs < self.config.taxi_gs_max_kt
        if rolling:
            self.state.motion_seen = True
            if self.state.rolling_since is None:
                self.state.rolling_since = now_mono
            elif (now_mono - self.state.rolling_since) >= self.config.taxi_roll_seconds:
                return True
        else:
            self.state.rolling_since = None
        return False

    def _print_final(self, plan: SimBriefFlightPlan, *, reason: str) -> None:
        if is_fenix_aircraft(plan):
            return
        if not self.settings.simbrief_ofp_ticket_enabled("loadsheet_final"):
            return
        values = self.state.final_values or build_preliminary_values(plan)
        width = self._ticket_width()
        body = render_loadsheet_ticket(plan, "FINAL", values, width=width)
        self._print_bundle([("loadsheet_final", body)], label=reason)

    def _bundle_fp_prelim(self, plan: SimBriefFlightPlan) -> PrintBundle:
        width = self._ticket_width()
        enabled = self.settings.simbrief_ofp_tickets()
        tickets: PrintBundle = []
        if "flight_plan" in enabled:
            tickets.append(
                ("flight_plan", render_flight_plan_ticket(plan, width=width))
            )
        if "takeoff_data" in enabled:
            tickets.append(
                ("takeoff_data", render_takeoff_data_ticket(plan, width=width))
            )
        # Fenix A32x has its own EFB loadsheet — do not print ours.
        if (
            "loadsheet_prelim" in enabled
            and not is_fenix_aircraft(plan)
        ):
            prelim = build_preliminary_values(plan)
            tickets.append(
                (
                    "loadsheet_prelim",
                    render_loadsheet_ticket(plan, "PRELIMINARY", prelim, width=width),
                )
            )
        return tickets

    def _ticket_width(self) -> int:
        settings = self.settings.as_printer_settings()
        return settings.characters_per_line()

    def _print_bundle(self, tickets: PrintBundle, *, label: str) -> None:
        printer_settings = self.settings.as_printer_settings()
        callsign = self.state.plan.callsign if self.state.plan else "OFP"

        def job() -> None:
            for index, (ticket_type, body) in enumerate(tickets):
                if index:
                    time.sleep(TICKET_GAP_SECONDS)
                self.print_manager.print_ticket(
                    body,
                    printer_settings,
                    callsign=callsign,
                    ticket_type=ticket_type,
                    sender="SIMBRIEF",
                )

        deferred = self.sterile.run_or_defer_simbrief(job)
        if deferred:
            reason = self.sterile.block_reason() or "hold"
            self.state.status = f"queued ({label}) · {reason}"
        log.info(
            "SimBrief print bundle %s tickets=%s deferred=%s reason=%s blocking=%s",
            label,
            len(tickets),
            deferred,
            self.sterile.block_reason(),
            self.sterile.is_blocking,
        )

    def _update_flight_phase(self, snapshot: SimSnapshot | None, now_mono: float) -> None:
        if snapshot is None or not snapshot.connected:
            return

        if snapshot.on_ground:
            gs = snapshot.ground_velocity_kt
            if self.config.taxi_gs_min_kt < gs < self.config.taxi_gs_max_kt:
                self.state.motion_seen = True

        in_flight_phases = {
            WatcherPhase.LOCKED,
            WatcherPhase.FINAL_PRINTED,
            WatcherPhase.AIRBORNE,
            WatcherPhase.POST_LANDING,
        }
        if self.state.phase not in in_flight_phases:
            return

        if not snapshot.on_ground:
            if self.state.airborne_since is None:
                self.state.airborne_since = now_mono
            self.state.on_ground_since = None
            airborne_for = now_mono - self.state.airborne_since
            if airborne_for >= self.config.airborne_debounce_seconds:
                if self.state.phase in {WatcherPhase.LOCKED, WatcherPhase.FINAL_PRINTED}:
                    if not self.state.final_printed:
                        self.state.missed_final_pending = True
                    self.state.phase = WatcherPhase.AIRBORNE
                    self.state.status = (
                        f"airborne · {self.state.plan.callsign if self.state.plan else ''}".strip()
                    )
                    self._persist()
            return

        # On ground
        if self.state.phase == WatcherPhase.AIRBORNE:
            if self.state.on_ground_since is None:
                self.state.on_ground_since = now_mono
            on_ground_for = now_mono - self.state.on_ground_since
            if on_ground_for >= self.config.landing_debounce_seconds:
                self.state.phase = WatcherPhase.POST_LANDING
                self.state.post_landing_since = now_mono
                self.state.status = "post-landing grace"
                self._persist()
            return

        if self.state.phase == WatcherPhase.POST_LANDING:
            started = self.state.post_landing_since or now_mono
            if (now_mono - started) >= self.config.post_landing_grace_seconds:
                self.unlock(reason="post-landing grace done")

    def _waiting_status(self, plan: SimBriefFlightPlan, now_utc: datetime) -> str:
        if plan.sched_out_utc is None:
            return "waiting for OFP with SOBT"
        if plan.sched_out_utc < (now_utc - self.config.sobt_late_grace):
            return f"waiting for new OFP (departure passed · {plan.callsign})"
        return f"waiting · latest {plan.callsign} not eligible"

    def _refresh_status(self, snapshot: SimSnapshot | None) -> None:
        if self.state.phase == WatcherPhase.POLLING and self.state.status.startswith("waiting"):
            return
        if self.sterile.is_sterile and self.state.phase != WatcherPhase.POLLING:
            base = self.state.status.split(" · sterile")[0]
            self.state.status = f"{base} · sterile"
        mismatch = self._mismatch_hint()
        if mismatch and "mismatch" not in self.state.status:
            self.state.status = f"{self.state.status} · {mismatch}"

    def _mismatch_hint(self) -> str | None:
        plan = self.state.plan
        if plan is None:
            return None
        cs = (self.settings.callsign() or "").strip().upper()
        reg = (self.settings.aircraft_registration() or "").strip().upper()
        hints: list[str] = []
        if cs and plan.callsign.upper() != cs:
            hints.append("callsign mismatch")
        if reg and plan.aircraft_reg.upper() != reg:
            hints.append("reg mismatch")
        return ", ".join(hints) if hints else None

    def _persist(self) -> None:
        blob: dict[str, object] = {
            "phase": self.state.phase.value,
            "ofp_id": self.state.ofp_id,
            "locked_at": self.state.locked_at,
            "final_printed": self.state.final_printed,
            "lock_printed": self.state.lock_printed,
            "motion_seen": self.state.motion_seen,
            "missed_final_pending": self.state.missed_final_pending,
            "airborne_since": self.state.airborne_since,
            "on_ground_since": self.state.on_ground_since,
            "post_landing_since": self.state.post_landing_since,
            "rolling_since": self.state.rolling_since,
            "doors_seen_open": self.state.doors_seen_open,
            "doors_closed_since": self.state.doors_closed_since,
            "status": self.state.status,
            "backoff_seconds": self.state.backoff_seconds,
            "next_poll_at": self.state.next_poll_at,
        }
        if self.state.plan is not None:
            blob["plan"] = self.state.plan.to_dict()
        if self.state.final_values is not None:
            blob["final_values"] = self.state.final_values.to_dict()
        self.settings.set_simbrief_lock_state(json.dumps(blob))

    def _restore(self) -> None:
        raw = self.settings.simbrief_lock_state()
        if not raw:
            return
        try:
            blob = json.loads(raw)
        except json.JSONDecodeError:
            return
        try:
            phase = WatcherPhase(str(blob.get("phase") or "polling"))
        except ValueError:
            phase = WatcherPhase.POLLING
        self.state.phase = phase
        self.state.ofp_id = blob.get("ofp_id")
        self.state.locked_at = blob.get("locked_at")
        self.state.final_printed = bool(blob.get("final_printed"))
        if "lock_printed" in blob:
            self.state.lock_printed = bool(blob.get("lock_printed"))
        else:
            self.state.lock_printed = phase in {
                WatcherPhase.LOCKED,
                WatcherPhase.FINAL_PRINTED,
                WatcherPhase.AIRBORNE,
                WatcherPhase.POST_LANDING,
            }
        self.state.motion_seen = bool(blob.get("motion_seen"))
        self.state.missed_final_pending = bool(blob.get("missed_final_pending"))
        self.state.airborne_since = blob.get("airborne_since")
        self.state.on_ground_since = blob.get("on_ground_since")
        self.state.post_landing_since = blob.get("post_landing_since")
        self.state.rolling_since = blob.get("rolling_since")
        self.state.doors_seen_open = bool(blob.get("doors_seen_open"))
        self.state.doors_closed_since = blob.get("doors_closed_since")
        self.state.status = str(blob.get("status") or phase.value)
        self.state.backoff_seconds = float(blob.get("backoff_seconds") or 0.0)
        self.state.next_poll_at = float(blob.get("next_poll_at") or 0.0)
        plan_blob = blob.get("plan")
        if isinstance(plan_blob, dict):
            try:
                self.state.plan = SimBriefFlightPlan.from_dict(plan_blob)
            except Exception:
                log.exception("failed to restore SimBrief plan")
                self.state.plan = None
        final_blob = blob.get("final_values")
        if isinstance(final_blob, dict):
            try:
                self.state.final_values = LoadsheetValues.from_dict(final_blob)
            except Exception:
                log.exception("failed to restore final loadsheet values")
                self.state.final_values = None
