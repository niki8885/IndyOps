"""
Pure invention math: success probability, decryptor effects, and the per-candidate
economics (cost per resulting BPC / run / unit, and downstream production profit).

Stdlib only. The same ``evaluate`` is the spec the Haskell optimizer mirrors, so
keep both sides identical (see app.adapters.invention_optimizer +
haskell/invention-optimizer). Constants verified against EVE University.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Optional

from app.services.manufacturing import SCC_SURCHARGE, adj_qty

# Invented T2 BPCs start at ME 2 / TE 4 before any decryptor.
BASE_T2_ME = 2
BASE_T2_TE = 4
INVENTION_COST_FACTOR = 0.02  # invention job base cost = 2% of the T2 product's manufacturing EIV


@dataclass(frozen=True)
class Decryptor:
    """A decryptor's invention modifiers. ``prob_mod`` is a percentage: +20 → ×1.20
    on the success chance. ``type_id`` is None for the no-decryptor option."""
    name: str
    type_id: Optional[int]
    prob_mod: int
    me_mod: int
    te_mod: int
    runs_mod: int


# The eight decryptors + "no decryptor". Modifiers per EVE University.
DECRYPTORS: list[Decryptor] = [
    Decryptor("No Decryptor", None, 0, 0, 0, 0),
    Decryptor("Accelerant", 34201, 20, 2, 10, 1),
    Decryptor("Attainment", 34202, 80, -1, 4, 4),
    Decryptor("Augmentation", 34203, -40, -2, 2, 9),
    Decryptor("Optimized Attainment", 34204, 90, 1, -2, 2),
    Decryptor("Optimized Augmentation", 34205, -10, 2, 0, 7),
    Decryptor("Parity", 34206, 50, 1, -2, 3),
    Decryptor("Process", 34207, 10, 3, 6, 0),
    Decryptor("Symmetry", 34208, 0, 1, 8, 2),
]
DECRYPTOR_BY_NAME = {d.name: d for d in DECRYPTORS}
DECRYPTOR_TYPE_IDS = [d.type_id for d in DECRYPTORS if d.type_id]


def success_probability(base_prob: float, encryption_lvl: int,
                        sci1_lvl: int, sci2_lvl: int, prob_mod: int) -> float:
    """P = base × (1 + (sci1+sci2)/30 + encryption/40) × (1 + decryptorMod/100), in [0,1]."""
    skill_factor = 1 + (sci1_lvl + sci2_lvl) / 30 + encryption_lvl / 40
    p = base_prob * skill_factor * (1 + prob_mod / 100)
    return min(1.0, max(0.0, p))


def invention_install(t2_manuf_eiv: float, index: float,
                      cost_role_pct: float = 0.0, facility_tax_pct: float = 0.0) -> float:
    """Per-attempt invention installation fee: 2% of the T2 product's manufacturing
    EIV, × system invention index (− structure cost bonus) + facility tax + SCC."""
    base = t2_manuf_eiv * INVENTION_COST_FACTOR
    system_cost = base * index
    gross = system_cost - system_cost * cost_role_pct / 100
    return gross + base * facility_tax_pct / 100 + base * SCC_SURCHARGE


@dataclass
class Material:
    qty: int
    price: float


def evaluate(*, base_prob: float, base_runs: int, units_per_run: int,
             datacore_cost: float, decryptor_price: float, invention_install_cost: float,
             manuf_install_per_run: float, sell_per_unit: float,
             materials: list[Material], mat_extra_mult: float,
             encryption: int, sci1: int, sci2: int, decryptor: Decryptor) -> dict:
    """
    Full economics for one (product × decryptor). The invented BPC's ME drives the
    downstream material cost, so cost is computed at ME = 2 + decryptor.me_mod.

      cost/attempt = datacores + decryptor + invention install
      cost/BPC     = cost/attempt ÷ success_probability
      cost/run     = cost/BPC ÷ resulting BPC runs
      unit cost    = (manufacturing cost/run + invention cost/run) ÷ units/run
      profit/unit  = sell − unit cost ; profit/run = profit/unit × units/run
    """
    prob = success_probability(base_prob, encryption, sci1, sci2, decryptor.prob_mod)
    bpc_runs = max(1, base_runs + decryptor.runs_mod)
    bpc_me = max(0, BASE_T2_ME + decryptor.me_mod)
    bpc_te = max(0, BASE_T2_TE + decryptor.te_mod)
    units = max(1, units_per_run)

    cost_per_attempt = datacore_cost + decryptor_price + invention_install_cost
    cost_per_bpc = cost_per_attempt / prob if prob > 0 else math.inf
    cost_per_run = cost_per_bpc / bpc_runs

    mat_cost = sum(adj_qty(m.qty, 1, bpc_me, mat_extra_mult) * m.price for m in materials)
    manuf_cost_per_run = mat_cost + manuf_install_per_run

    if math.isinf(cost_per_run):
        cost_per_unit = math.inf
        profit_per_unit = -math.inf
        profit_per_run = -math.inf
        margin_pct = -100.0
    else:
        cost_per_unit = (manuf_cost_per_run + cost_per_run) / units
        profit_per_unit = sell_per_unit - cost_per_unit
        profit_per_run = profit_per_unit * units
        margin_pct = (profit_per_unit / cost_per_unit * 100) if cost_per_unit > 0 else 0.0

    # Raw floats (no rounding) so the optimizer ranks identically to the Haskell
    # engine; callers round for display. None marks an unattainable (prob 0) result.
    none_if_inf = lambda x: None if math.isinf(x) else x  # noqa: E731
    return {
        "decryptor": decryptor.name,
        "probability": prob,
        "bpc_runs": bpc_runs, "bpc_me": bpc_me, "bpc_te": bpc_te,
        "cost_per_attempt": cost_per_attempt,
        "cost_per_bpc": none_if_inf(cost_per_bpc),
        "cost_per_run": none_if_inf(cost_per_run),
        "manuf_cost_per_run": manuf_cost_per_run,
        "units_per_run": units,
        "sell_per_unit": sell_per_unit,
        "cost_per_unit": none_if_inf(cost_per_unit),
        "profit_per_unit": none_if_inf(profit_per_unit),
        "profit_per_run": none_if_inf(profit_per_run),
        "margin_pct": margin_pct,
    }
