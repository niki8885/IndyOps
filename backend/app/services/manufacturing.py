"""
Pure manufacturing cost/profit calculation.

Extracted from manufacturing_router (``_run_calculation``/``_adj_qty``/
``_adj_time``). The router resolves the blueprint, prices and facility defaults
(I/O) then builds a ``CalcInput``; this module turns that into a ``CalcResult``.
``asdict(result)`` reproduces the exact JSON the API used to return (and that the
frontend persists as ``calc_snapshot``). math only — no I/O.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

SCC_SURCHARGE = 0.04   # fixed 4% CCP surcharge on EIV


# ── inputs ──────────────────────────────────────────────────────────────────

@dataclass
class Material:
    type_id: int
    name: str
    base_qty: int
    unit_cost: float


@dataclass
class CalcInput:
    product_name: str
    product_qty_per_run: int
    runs: int
    me: int
    te: int
    base_time_per_run: int
    materials: list[Material]
    output_price: float
    bpc_cost: float
    broker_fee_pct: float
    system_cost_index: float            # fraction, e.g. 0.0593
    facility_tax_pct: float
    structure_bonus_pct: float = 0.0
    estimated_item_value: Optional[float] = None   # single-job EIV; scaled to batch
    material_bonus_pct: float = 0.0     # rig ME (security-scaled)
    time_bonus_pct: float = 0.0         # rig TE
    material_role_pct: float = 0.0      # structure role ME (e.g. EC −1%)
    time_role_pct: float = 0.0          # structure role TE
    windows: int = 1                    # parallel production slots, each `runs` runs


# ── outputs ─────────────────────────────────────────────────────────────────

@dataclass
class MaterialRow:
    type_id: int
    name: str
    base_qty: int
    adj_qty: int
    saved: int
    unit_cost: float
    gross_cost: float
    net_cost: float


@dataclass
class OutputResult:
    name: str
    quantity: int
    unit_price: float
    gross_sell: float
    net_sell: float


@dataclass
class JobCost:
    estimated_item_value: float
    system_cost_index_pct: float
    system_cost: float
    structure_bonus: float
    gross_install_cost: float
    facility_tax: float
    scc_surcharge: float
    net_install_cost: float


@dataclass
class JobTime:
    seconds: int
    hours: float
    total_slot_hours: float


@dataclass
class Results:
    total_material_cost: float
    total_install_cost: float
    total_costs: float
    total_sell: float
    profit: float
    margin_pct: float


@dataclass
class CalcResult:
    windows: int
    runs_per_window: int
    output: OutputResult
    materials: list[MaterialRow]
    materials_total_gross: float
    materials_total_net: float
    job_cost: JobCost
    bpc_cost: float
    job_time: JobTime
    results: Results


# ── calculation ─────────────────────────────────────────────────────────────

def adj_qty(base_qty: int, runs: int, me: int, extra_mult: float = 1.0) -> int:
    """
    Material qty after blueprint ME and an extra multiplier (rig + structure role,
    combined multiplicatively by the caller). Always ≥ runs.
    """
    return max(runs, math.ceil(base_qty * runs * (1 - me / 100) * extra_mult))


def adj_time(base_time: int, runs: int, te: int, extra_mult: float = 1.0) -> int:
    return math.ceil(base_time * runs * (1 - te / 100) * extra_mult)


def run_calculation(inp: CalcInput) -> CalcResult:
    w = max(1, int(inp.windows))

    total_output = inp.product_qty_per_run * inp.runs * w
    gross_sell = total_output * inp.output_price
    net_sell = gross_sell * (1 - inp.broker_fee_pct / 100)

    # rig and structure-role bonuses stack multiplicatively, like EVE
    mat_mult = (1 - inp.material_bonus_pct / 100) * (1 - inp.material_role_pct / 100)
    time_mult = (1 - inp.time_bonus_pct / 100) * (1 - inp.time_role_pct / 100)

    mat_rows: list[MaterialRow] = []
    total_mat_cost = 0.0
    for m in inp.materials:
        # ME rounds per job, then × number of windows
        adj_job = adj_qty(m.base_qty, inp.runs, inp.me, mat_mult)
        adj = adj_job * w
        base = m.base_qty * inp.runs * w
        gross_cost = adj * m.unit_cost
        total_mat_cost += gross_cost
        mat_rows.append(MaterialRow(
            type_id=m.type_id,
            name=m.name,
            base_qty=base,
            adj_qty=adj,
            saved=base - adj,
            unit_cost=m.unit_cost,
            gross_cost=round(gross_cost, 2),
            net_cost=round(gross_cost, 2),
        ))

    total_mat_cost = round(total_mat_cost, 2)

    # EIV passed in is single-job; scale to the whole batch
    eiv = inp.estimated_item_value * w if (inp.estimated_item_value and inp.estimated_item_value > 0) else total_mat_cost
    system_cost = round(eiv * inp.system_cost_index, 2)
    structure_bonus = round(system_cost * inp.structure_bonus_pct / 100, 2)
    gross_install = round(system_cost - structure_bonus, 2)
    facility_tax_isk = round(eiv * inp.facility_tax_pct / 100, 2)
    scc_surcharge = round(eiv * SCC_SURCHARGE, 2)
    net_install = round(gross_install + facility_tax_isk + scc_surcharge, 2)

    bpc_total = round(inp.bpc_cost * w, 2)                                # one BPC per window
    job_time_s = adj_time(inp.base_time_per_run, inp.runs, inp.te, time_mult)   # per-job time

    total_costs = round(total_mat_cost + bpc_total + net_install, 2)
    profit = round(net_sell - total_costs, 2)
    margin = round(profit / total_costs * 100, 2) if total_costs else 0.0

    return CalcResult(
        windows=w,
        runs_per_window=inp.runs,
        output=OutputResult(
            name=inp.product_name,
            quantity=total_output,
            unit_price=inp.output_price,
            gross_sell=round(gross_sell, 2),
            net_sell=round(net_sell, 2),
        ),
        materials=mat_rows,
        materials_total_gross=total_mat_cost,
        materials_total_net=total_mat_cost,
        job_cost=JobCost(
            estimated_item_value=round(eiv, 2),
            system_cost_index_pct=round(inp.system_cost_index * 100, 4),
            system_cost=system_cost,
            structure_bonus=structure_bonus,
            gross_install_cost=gross_install,
            facility_tax=facility_tax_isk,
            scc_surcharge=scc_surcharge,
            net_install_cost=net_install,
        ),
        bpc_cost=bpc_total,
        job_time=JobTime(
            seconds=job_time_s,
            hours=round(job_time_s / 3600, 2),
            total_slot_hours=round(job_time_s / 3600 * w, 2),
        ),
        results=Results(
            total_material_cost=total_mat_cost,
            total_install_cost=net_install,
            total_costs=total_costs,
            total_sell=round(net_sell, 2),
            profit=profit,
            margin_pct=margin,
        ),
    )
