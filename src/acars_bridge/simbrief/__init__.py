"""SimBrief OFP fetch, tickets, and auto-print watcher."""

from acars_bridge.simbrief.models import SimBriefFlightPlan, is_eligible_for_autoprint

__all__ = ["SimBriefFlightPlan", "is_eligible_for_autoprint"]
