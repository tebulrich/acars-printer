from __future__ import annotations

import random
from dataclasses import dataclass

from acars_bridge.simbrief.models import SimBriefFlightPlan

_PAX_WEIGHT_KG = 84.0
_BAG_WEIGHT_PER_PAX_KG = 20.0
_KG_TO_LBS = 2.2046226218


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


def _is_pounds(units: str) -> bool:
    return units.strip().lower() in {"lbs", "lb"}


def _from_kg(kg: float, units: str) -> float:
    return kg * _KG_TO_LBS if _is_pounds(units) else kg


def build_preliminary_values(plan: SimBriefFlightPlan) -> LoadsheetValues:
    return LoadsheetValues(
        pax_count=_parse_int(plan.pax_count),
        cargo_weight=_parse_float(plan.cargo_weight),
        zfw=_parse_float(plan.zfw),
        tow=_parse_float(plan.tow),
    )


def build_final_values(
    plan: SimBriefFlightPlan,
    *,
    randomize: bool = False,
    rng: random.Random | None = None,
) -> LoadsheetValues:
    if not randomize:
        return build_preliminary_values(plan)

    rng = rng or random.Random()
    pax = _parse_int(plan.pax_count)
    cargo = _parse_float(plan.cargo_weight)
    zfw = _parse_float(plan.zfw)
    tow = _parse_float(plan.tow)
    takeoff_fuel = _parse_float(plan.takeoff_fuel)

    pax_delta = sum(rng.randint(0, 2) - 1 for _ in range(3))
    pax_weight = _from_kg(_PAX_WEIGHT_KG, plan.units)
    bag_weight = _from_kg(_BAG_WEIGHT_PER_PAX_KG, plan.units)
    cargo_delta = pax_delta * bag_weight
    weight_delta = pax_delta * pax_weight + cargo_delta

    new_pax = max(0, pax + pax_delta)
    new_cargo = max(0.0, cargo + cargo_delta)
    new_zfw = zfw + weight_delta
    new_tow = new_zfw + takeoff_fuel

    return LoadsheetValues(
        pax_count=new_pax,
        cargo_weight=new_cargo,
        zfw=new_zfw,
        tow=new_tow,
        pax_delta=pax_delta,
        cargo_delta=cargo_delta,
        zfw_delta=new_zfw - zfw,
        tow_delta=new_tow - tow,
    )
