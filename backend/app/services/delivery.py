"""
Pure delivery-cost maths for the Inventory → Delivery feature.

Two shipping modes:
  * regular — a freighter hauling through gates: cost = jumps × ISK/jump/m³ × volume.
  * jf      — a jump freighter burning isotopes: cost = trips × ly × isotopes/ly × price.

No DB / HTTP here — the router resolves system coordinates (SDE) and the gate-jump
count (ESI route) and feeds the numbers in. Everything is unit-testable.
"""
from __future__ import annotations

import math
import secrets
import string

# 1 light year in metres — SDE solar-system x/y/z are stored in metres.
LY_METERS = 9.4607304725808e15

# A jump freighter's effective cargo hold (m³). Fixed per the spec — one "trip"
# moves at most this much, so a big haul needs several jumps.
JF_CARGO_M3 = 350_000.0

# The four jump freighters and the isotope each one burns.
JF_ISOTOPES = {
    "Ark": "Helium Isotopes",       # Amarr
    "Rhea": "Nitrogen Isotopes",    # Caldari
    "Nomad": "Hydrogen Isotopes",   # Minmatar
    "Anshar": "Oxygen Isotopes",    # Gallente
}


def light_years(x1: float, y1: float, z1: float,
                x2: float, y2: float, z2: float) -> float:
    """Straight-line distance between two systems, in light years."""
    d = math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2)
    return d / LY_METERS


def trips_for(total_volume: float, cargo: float = JF_CARGO_M3) -> int:
    """Number of jump-freighter loads needed to move ``total_volume`` m³."""
    if total_volume <= 0:
        return 0
    return math.ceil(total_volume / cargo)


def jf_cost(total_volume: float, ly: float, isotopes_per_ly: float,
            isotope_price: float, round_trip: bool = False,
            cargo: float = JF_CARGO_M3) -> dict:
    """
    Jump-freighter shipping cost.

    isotopes per jump = ly × isotopes_per_ly; one trip = one jump (×2 if it has to
    fly home empty). total isotopes = trips × per-jump (× 2 round-trip).
    """
    trips = trips_for(total_volume, cargo)
    legs = 2 if round_trip else 1
    isotopes_per_jump = max(ly, 0.0) * max(isotopes_per_ly, 0.0)
    total_isotopes = trips * isotopes_per_jump * legs
    total_cost = total_isotopes * max(isotope_price, 0.0)
    cost_per_m3 = total_cost / total_volume if total_volume > 0 else 0.0
    return {
        "trips": trips,
        "isotopes_per_jump": round(isotopes_per_jump, 2),
        "total_isotopes": round(total_isotopes, 2),
        "total_cost": round(total_cost, 2),
        "cost_per_m3": round(cost_per_m3, 2),
    }


def regular_cost(total_volume: float, jumps: int, isk_per_jump_m3: float) -> dict:
    """Gate-freighter shipping cost: jumps × ISK/jump/m³ × volume."""
    total_cost = max(jumps, 0) * max(isk_per_jump_m3, 0.0) * max(total_volume, 0.0)
    cost_per_m3 = total_cost / total_volume if total_volume > 0 else 0.0
    return {
        "total_cost": round(total_cost, 2),
        "cost_per_m3": round(cost_per_m3, 2),
    }


def gen_code(n: int = 10) -> str:
    """Random uppercase-alphanumeric code (used as the delivery's unique tag)."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def build_comment(project: str | None, date: str, code: str, target: str | None,
                  collateral: float, cost: float) -> str:
    """
    Human/contract-ready note, e.g.
        "Helium Run | 2026-06-17 | 7QF3KZ9P2A | → Jita | coll 1.20B ISK | cost 0 ISK"
    Mirrors the pipe-separated contractNote style used in the Parse tab.
    """
    parts = [
        project or "Delivery",
        date,
        code,
        f"→ {target}" if target else None,
        f"coll {_isk(collateral)}",
        f"cost {_isk(cost)}",
    ]
    return " | ".join(p for p in parts if p)


def _isk(v: float) -> str:
    """Compact ISK formatting (mirrors the frontend fmtIsk)."""
    n = float(v or 0)
    if n >= 1e9:
        return f"{n / 1e9:.2f}B ISK"
    if n >= 1e6:
        return f"{n / 1e6:.2f}M ISK"
    return f"{n:,.0f} ISK"
