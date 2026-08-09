from __future__ import annotations

from dataclasses import dataclass

from acars_bridge.simbrief.models import SimBriefFlightPlan


@dataclass(frozen=True, slots=True)
class LoadsheetValues:
    pax_count: int
    cargo_weight: float
    zfw: float
    tow: float
    pax_delta: int | None = None
    cargo_delta: float | None = None
    zfw_delta: float | None = None
    tow_delta: float | None = None

    def to_dict(self) -> dict[str, float | int | None]:
        return {
            "pax_count": self.pax_count,
            "cargo_weight": self.cargo_weight,
            "zfw": self.zfw,
            "tow": self.tow,
            "pax_delta": self.pax_delta,
            "cargo_delta": self.cargo_delta,
            "zfw_delta": self.zfw_delta,
            "tow_delta": self.tow_delta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> LoadsheetValues:
        def _num(key: str, default: float = 0.0) -> float:
            try:
                return float(data.get(key, default) or default)
            except (TypeError, ValueError):
                return default

        def _opt_int(key: str) -> int | None:
            raw = data.get(key)
            if raw is None:
                return None
            try:
                return int(raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        def _opt_float(key: str) -> float | None:
            raw = data.get(key)
            if raw is None:
                return None
            try:
                return float(raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        return cls(
            pax_count=int(_num("pax_count")),
            cargo_weight=_num("cargo_weight"),
            zfw=_num("zfw"),
            tow=_num("tow"),
            pax_delta=_opt_int("pax_delta"),
            cargo_delta=_opt_float("cargo_delta"),
            zfw_delta=_opt_float("zfw_delta"),
            tow_delta=_opt_float("tow_delta"),
        )


def _parse_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _parse_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_preliminary_values(plan: SimBriefFlightPlan) -> LoadsheetValues:
    return LoadsheetValues(
        pax_count=_parse_int(plan.pax_count),
        cargo_weight=_parse_float(plan.cargo_weight),
        zfw=_parse_float(plan.zfw),
        tow=_parse_float(plan.tow),
    )


def build_final_values(plan: SimBriefFlightPlan) -> LoadsheetValues:
    """Final loadsheet uses the same SimBrief figures as preliminary (no invented deltas)."""
    return build_preliminary_values(plan)
