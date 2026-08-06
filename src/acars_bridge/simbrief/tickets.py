from __future__ import annotations

import re
import textwrap

from acars_bridge.simbrief.loadsheet import LoadsheetValues
from acars_bridge.simbrief.models import SimBriefFlightPlan

_PLACEHOLDER = re.compile(r"\{(\w+)\}")

_FLIGHT_PLAN_TEMPLATE = """
**ACARS START**
===
**{Callsign}**
{AircraftReg}
---
{OriginIcao}/{OriginIata}  ->  {DestIcao}/{DestIata}
ALTN: {AlternateIcao}
---
Route:
{Route}
---
Cruise Alt:|{CruiseAltitude}
Distance:|{DistanceNm} nm
Flight Time:|{FlightTimeFormatted}
---
STD (out):|{SchedOutZulu}
STA (in):|{SchedInZulu}
---
Block Fuel:|{BlockFuel} {Units}
Taxi Fuel:|{TaxiFuel} {Units}
---
EZFW:|{Zfw} {Units}
ETOW:|{Tow} {Units}
---
Pax:|{PaxCount}
Cargo:|{CargoWeight} {Units}
===
**ACARS END**
""".strip()


def _wrap(text: str, width: int) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    for raw in text.splitlines() or [""]:
        if not raw:
            lines.append("")
            continue
        lines.extend(textwrap.wrap(raw, width=width, replace_whitespace=False) or [raw])
    return lines


def _divider(width: int, char: str = "-") -> str:
    return char * max(8, width)


def _key_value(label: str, value: str, width: int) -> list[str]:
    combined = label + value
    if len(combined) >= width:
        return [label, value.rjust(width)[:width]]
    pad = width - len(combined)
    return [label + (" " * pad) + value]


def render_flight_plan_ticket(plan: SimBriefFlightPlan, *, width: int = 32) -> str:
    values = plan.placeholder_map()
    out: list[str] = []
    for raw_line in _FLIGHT_PLAN_TEMPLATE.splitlines():
        line = raw_line.strip("\n")
        if line.startswith("#"):
            continue
        if not line.strip():
            out.append("")
            continue
        if line.strip() == "---":
            out.append(_divider(width, "-"))
            continue
        if line.strip() == "===":
            out.append(_divider(width, "="))
            continue

        def repl(match: re.Match[str]) -> str:
            return values.get(match.group(1), "N/A")

        line = _PLACEHOLDER.sub(repl, line)
        bold = False
        if line.startswith("**") and line.endswith("**") and len(line) > 4:
            line = line[2:-2]
            bold = True
        if "|" in line and not line.strip().startswith("Route"):
            left, right = line.split("|", 1)
            for piece in _key_value(left, right, width):
                out.append(piece.upper() if bold else piece)
            continue
        for wrapped in _wrap(line, width):
            out.append(wrapped.upper() if bold else wrapped)
    out.append("")
    return "\n".join(out)


def _fmt_weight(weight: float) -> str:
    return f"{round(weight):.0f}"


def _fmt_signed_int(value: int) -> str:
    return f"+{value}" if value >= 0 else str(value)


def _fmt_signed_weight(value: float) -> str:
    body = _fmt_weight(value)
    return f"+{body}" if value >= 0 else body


def _fmt_pax(values: LoadsheetValues) -> str:
    text = str(values.pax_count)
    if values.pax_delta is not None:
        text += f" ({_fmt_signed_int(values.pax_delta)})"
    return text


def _fmt_weight_delta(weight: float, delta: float | None, units: str) -> str:
    text = f"{_fmt_weight(weight)} {units}"
    if delta is not None:
        text += f" ({_fmt_signed_weight(delta)})"
    return text


def render_loadsheet_ticket(
    plan: SimBriefFlightPlan,
    label: str,
    values: LoadsheetValues,
    *,
    width: int = 32,
) -> str:
    lines: list[str] = [
        "ACARS START",
        "LOAD SHEET",
        label.upper(),
        _divider(width, "="),
        f"{plan.callsign}  {plan.origin_icao}-{plan.dest_icao}",
        plan.aircraft_reg,
        _divider(width, "-"),
    ]
    lines.extend(_key_value("PAX:", _fmt_pax(values), width))
    lines.extend(
        _key_value(
            "CARGO:",
            _fmt_weight_delta(values.cargo_weight, values.cargo_delta, plan.units),
            width,
        )
    )
    lines.append(_divider(width, "-"))
    lines.extend(
        _key_value(
            "ZFW:",
            _fmt_weight_delta(values.zfw, values.zfw_delta, plan.units),
            width,
        )
    )
    lines.extend(_key_value("MAX ZFW:", f"{plan.max_zfw} {plan.units}", width))
    lines.extend(
        _key_value(
            "TOW:",
            _fmt_weight_delta(values.tow, values.tow_delta, plan.units),
            width,
        )
    )
    lines.extend(_key_value("MAX TOW:", f"{plan.max_tow} {plan.units}", width))
    lines.append(_divider(width, "-"))
    lines.extend(_key_value("TAKEOFF FUEL:", f"{plan.takeoff_fuel} {plan.units}", width))
    lines.append(_divider(width, "="))
    lines.append("ACARS END")
    lines.append("")
    return "\n".join(lines)
