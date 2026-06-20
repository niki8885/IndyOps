from __future__ import annotations
import math
from dataclasses import dataclass, asdict
from typing import Optional

from app.services.manufacturing import SCC_SURCHARGE, adj_qty, adj_time

# CUMULATIVE time to research a blueprint from level 0 *to* this level (rank-1
# baseline, seconds); level 0 = 0. Researching A→B uses the difference of the two
# entries, and BOTH the time and the cost scale by that span ÷ the level-1 value
# (105 s). Verified against EVE University: reach ME4 = 1,414 s (24 m), reach ME10
# = 256,000 s (~3 days). The SDE activity-3/4 base time already folds in blueprint
# rank (a rank-1 blueprint's base research time is the level-1 value, 105 s).
RESEARCH_LEVEL_SECONDS = {
    0: 0, 1: 105, 2: 250, 3: 595, 4: 1414, 5: 3360,
    6: 8000, 7: 19000, 8: 45255, 9: 107700, 10: 256000,
}
_BASE_LEVEL_SECONDS = RESEARCH_LEVEL_SECONDS[1]  # 105
COPY_COST_FACTOR = 0.02
MAX_ME = 10
MAX_TE = 20

# The SCC surcharge is 4% of the job cost base for manufacturing / copying / invention,
# but EVE charges only HALF (2%) on the PTV of ME/TE *research* jobs — verified in-game:
# index 8.91% (−25% rig/role) + 2% SCC on a 42.65M PTV reproduces the 3,733,940 ISK total.
RESEARCH_SCC = SCC_SURCHARGE / 2


# job installation cost

@dataclass
class JobCost:
    base_cost: float  # EIV-derived job base cost (the index/tax operate on this)
    system_cost_index: float
    system_cost: float  # base_cost × index
    structure_bonus: float  # cost reduction from EC role + cost rigs
    facility_tax: float
    scc_surcharge: float
    install_cost: float


def _install(base_cost: float, index: float, cost_role_pct: float, facility_tax_pct: float,
             scc_pct: float = SCC_SURCHARGE) -> JobCost:
    """Installation cost from a job base cost, mirroring services.manufacturing.
    ``scc_pct`` is the SCC surcharge rate (4% normally, 2% for ME/TE research)."""
    system_cost = base_cost * index
    structure_bonus = system_cost * cost_role_pct / 100
    gross = system_cost - structure_bonus
    tax = base_cost * facility_tax_pct / 100
    scc = base_cost * scc_pct
    return JobCost(
        base_cost=round(base_cost, 2),
        system_cost_index=index,
        system_cost=round(system_cost, 2),
        structure_bonus=round(structure_bonus, 2),
        facility_tax=round(tax, 2),
        scc_surcharge=round(scc, 2),
        install_cost=round(gross + tax + scc, 2),
    )


def _level_ratio(from_lvl: int, to_lvl: int) -> float:
    """Level multiplier for researching ``from_lvl`` → ``to_lvl``: the cumulative
    research-time span (``MODIFIER[to] − MODIFIER[from]``) ÷ the level-1 value.
    Drives both research duration and research cost (CCP scales cost by the same
    span, normalised to a level-1 research)."""
    if to_lvl <= from_lvl:
        return 0.0
    return (RESEARCH_LEVEL_SECONDS[to_lvl] - RESEARCH_LEVEL_SECONDS[from_lvl]) / _BASE_LEVEL_SECONDS


# copying

def copy_plan(
        base_copy_time_per_run: int,
        manuf_eiv_1run: float,
        runs_per_copy: int,
        copies: int,
        copy_index: float,
        cost_role_pct: float = 0.0,
        facility_tax_pct: float = 0.0,
        time_mult: float = 1.0,
        time_bonus_pct: float = 0.0,
) -> dict:
    """Time + ISK to copy a blueprint into ``copies`` BPCs of ``runs_per_copy`` runs each."""
    runs_per_copy = max(1, int(runs_per_copy))
    copies = max(1, int(copies))
    total_runs = runs_per_copy * copies
    time_s = math.ceil(base_copy_time_per_run * total_runs * time_mult * (1 - time_bonus_pct / 100))
    base_cost = manuf_eiv_1run * COPY_COST_FACTOR * total_runs
    cost = _install(base_cost, copy_index, cost_role_pct, facility_tax_pct)
    return {
        "runs_per_copy": runs_per_copy,
        "copies": copies,
        "total_runs": total_runs,
        "time_s": time_s,
        "time_per_copy_s": math.ceil(time_s / copies),
        "cost": asdict(cost),
    }


# ME / TE research

def research_time(base_time: int, from_lvl: int, to_lvl: int,
                  time_mult: float = 1.0, time_bonus_pct: float = 0.0) -> int:
    """Seconds to research from ``from_lvl`` to ``to_lvl`` (0 if not advancing)."""
    ratio = _level_ratio(from_lvl, to_lvl)
    if ratio <= 0:
        return 0
    return math.ceil(base_time * ratio * time_mult * (1 - time_bonus_pct / 100))


def research_cost(manuf_eiv_1run: float, from_lvl: int, to_lvl: int, index: float,
                  cost_role_pct: float = 0.0, facility_tax_pct: float = 0.0) -> JobCost:
    """Install cost to research from ``from_lvl`` to ``to_lvl`` (ME/TE: 2% SCC)."""
    base_cost = manuf_eiv_1run * COPY_COST_FACTOR * _level_ratio(from_lvl, to_lvl)
    return _install(base_cost, index, cost_role_pct, facility_tax_pct, scc_pct=RESEARCH_SCC)


def me_material_savings(materials: list[dict], from_me: int, to_me: int,
                        mat_extra_mult: float = 1.0) -> tuple[list[dict], float]:
    """
    Per-run material rows comparing ME ``from`` vs ``to``. ``materials`` items carry
    ``type_id, name, base_qty, unit_price``. Quantities use the production rounding
    (``adj_qty``: ceil, never below the run count), so a material whose count is
    unchanged by the ME bump is flagged ``me_no_effect`` — e.g. base qty 1, where
    −10% still rounds to 1.
    """
    rows: list[dict] = []
    total_saved = 0.0
    for m in materials:
        base_qty = int(m["base_qty"])
        unit = float(m.get("unit_price") or 0.0)
        q_from = adj_qty(base_qty, 1, from_me, mat_extra_mult)
        q_to = adj_qty(base_qty, 1, to_me, mat_extra_mult)
        saved_units = q_from - q_to
        saved_isk = saved_units * unit
        total_saved += saved_isk
        rows.append({
            "type_id": m["type_id"], "name": m.get("name"),
            "base_qty": base_qty, "unit_price": round(unit, 2),
            "qty_from": q_from, "qty_to": q_to,
            "saved_units": saved_units, "saved_isk": round(saved_isk, 2),
            "me_no_effect": saved_units == 0,
        })
    return rows, round(total_saved, 2)


def te_time_saving_per_run(base_manuf_time: int, from_te: int, to_te: int,
                           prod_time_mult: float = 1.0) -> int:
    """Manufacturing seconds saved *per run* by raising TE from ``from_te`` to ``to_te``."""
    t_from = adj_time(base_manuf_time, 1, from_te, prod_time_mult)
    t_to = adj_time(base_manuf_time, 1, to_te, prod_time_mult)
    return t_from - t_to


def payback_runs(research_install_cost: float, per_run_saving_isk: float) -> Optional[float]:
    """Production runs to recoup the ME research ISK (None if it never pays back)."""
    if per_run_saving_isk and per_run_saving_isk > 0:
        return round(research_install_cost / per_run_saving_isk, 1)
    return None


def time_payback_runs(research_time_s: float, per_run_time_saving_s: float) -> Optional[float]:
    """Production runs over which the faster TE jobs recoup the TE research time."""
    if per_run_time_saving_s and per_run_time_saving_s > 0:
        return round(research_time_s / per_run_time_saving_s, 1)
    return None
