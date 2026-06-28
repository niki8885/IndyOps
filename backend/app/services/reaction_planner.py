"""
Reaction Planner core — the batch ranking layer on top of the chain solver.

The chain core (:mod:`app.services.chain`) costs ONE target at a time. The planner
sweeps a *set* of candidate products (final reaction products + T2 components) and,
for each, answers: what does it cost to build from scratch, what is the ROI and the
income per hour, and — for a T2 component — is it cheaper to build its reactions
*from zero* or to *buy* the finished reaction intermediates.

This module is **pure** (stdlib + the chain/scheduling cores only — no DB, no market,
no subprocess). It is the Python *oracle* that the native Haskell engine
(``haskell/chain-engine`` ``reaction-planner`` executable) mirrors bit-for-bit, exactly
like :mod:`app.services.chain` mirrors ``Chain.Solver``. Money/ratio fields are exact
``Fraction`` at runtime (the ``float`` annotations are documentation) so the two engines
match on strict equality, not a float epsilon. See [[indyops-chain-calculator]] and
[[indyops-service-layering]].
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional

from app.services.chain import (
    ChainPlan, ChainRequest, MANUFACTURING, REACTION,
    solve_chain, to_request_dict as _chain_to_request_dict,
)
from app.services.scheduling import stage_schedule

# Practical batch size for an intermediate component blueprint job ("components always
# 10–20"): the planner marks each made *component* (intermediate manufacturing node) with
# a recommended per-job batch clamped to this band so reaction slots aren't starved by
# one-off component jobs. Presentation only — does not change costs.
BATCH_LO = 10
BATCH_HI = 20


def _frac(x) -> Optional[Fraction]:
    """float → exact *decimal* Fraction (matches the chain core / Haskell decimal parse)."""
    return Fraction(str(x)) if x is not None else None


# ── contract: request ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SellConfig:
    """How the finished product sells, for the ROI / income-per-hour numerator.

    ``unit_price`` is the gross sell quote (Jita sell or C-J sell). ``sales_tax_pct`` and
    ``broker_fee_pct`` are the selling character's reduced rates; ``freight_per_unit`` is
    the haul cost to the sell hub. Net unit revenue =
    ``unit_price·(1 − (tax+broker)/100) − freight``.
    """
    unit_price: float
    sales_tax_pct: float = 0.0
    broker_fee_pct: float = 0.0
    freight_per_unit: float = 0.0


@dataclass(frozen=True)
class Candidate:
    """One product to evaluate.

    ``scratch`` is the from-scratch ``ChainRequest`` (target force-made; reactions
    force-made down to raw moon goo). ``bought`` is the optional "buy the finished
    reaction intermediates" variant (T2 components only — target force-made, reaction
    nodes force-bought); when present the result carries a scratch-vs-bought delta.
    """
    type_id: int
    name: str
    sell: SellConfig
    scratch: ChainRequest
    bought: Optional[ChainRequest] = None


# ── contract: result ─────────────────────────────────────────────────────────

@dataclass
class ScratchDelta:
    cheaper: str            # "scratch" | "bought" (equal → "scratch")
    scratch_cost: float     # total make cost building the reactions from zero
    bought_cost: float      # total make cost buying the finished reaction intermediates
    delta: float            # bought_cost − scratch_cost (>0 → scratch is cheaper)


@dataclass
class BlueprintLine:
    type_id: int
    name: str
    activity: int           # 1 manufacturing / 11 reaction
    runs: int               # total runs needed across all jobs of this node
    jobs: int               # number of (30-day-capped) jobs the core emitted
    qty_out: int            # total units produced
    # batch annotation (filled by ``batch_components``; defaults keep it parity-neutral)
    is_component: bool = False     # an intermediate manufacturing node (not the target)
    batch_size: int = 0            # recommended per-job batch (10–20) for a component
    batches: int = 0               # number of such batches


@dataclass
class CandidateResult:
    type_id: int
    name: str
    target_qty: int
    decision: str               # the target's decision: "make" (planner force-makes) / "buy"
    unit_make_cost: float
    total_make_cost: float
    unit_sell: float            # net per-unit revenue (after tax/broker/freight)
    revenue: float              # net revenue for the whole batch
    profit: float               # revenue − total_make_cost
    roi: float                  # profit / total_make_cost (0 when cost is 0)
    total_time_s: int           # makespan with the given slots
    react_time_s: int           # Σ reaction job time (slot-seconds)
    man_time_s: int             # Σ manufacturing job time (slot-seconds)
    isk_per_hour: float         # profit / (makespan hours)
    isk_per_slot_hour: float    # profit / (total slot-hours of work)
    runs_by_activity: dict      # {1: n_mfg_runs, 11: n_react_runs}
    total_stages: int
    peak_man: int
    peak_react: int
    blueprints: list            # list[BlueprintLine]
    scratch_vs_bought: Optional[ScratchDelta] = None


# ── core ─────────────────────────────────────────────────────────────────────

def _aggregate_blueprints(plan: ChainPlan) -> list[BlueprintLine]:
    """One line per made node: total runs / jobs / output, from the plan's jobs."""
    agg: dict[int, BlueprintLine] = {}
    for j in plan.jobs:
        line = agg.get(j.type_id)
        if line is None:
            agg[j.type_id] = BlueprintLine(
                type_id=j.type_id, name=j.name, activity=j.activity,
                runs=j.runs, jobs=1, qty_out=j.qty_out)
        else:
            line.runs += j.runs
            line.jobs += 1
            line.qty_out += j.qty_out
    return sorted(agg.values(), key=lambda b: (b.activity, b.type_id))


def _metrics_from_plan(plan: ChainPlan, sell: SellConfig, man_slots: int, react_slots: int):
    """Schedule + money metrics for one solved plan. Pure, exact (Fraction)."""
    schedule = stage_schedule(plan.jobs, man_slots, react_slots)
    react_time_s = sum(j.time_s for j in plan.jobs if j.slot_kind == "reaction")
    man_time_s = sum(j.time_s for j in plan.jobs if j.slot_kind != "reaction")
    runs_by_activity = {MANUFACTURING: 0, REACTION: 0}
    for j in plan.jobs:
        runs_by_activity[j.activity] = runs_by_activity.get(j.activity, 0) + j.runs

    qty = plan.target_qty
    total_cost = plan.total_cost if plan.total_cost is not None else Fraction(0)
    unit_cost = plan.unit_cost if plan.unit_cost is not None else Fraction(0)

    gross = _frac(sell.unit_price) or Fraction(0)
    fee = ((_frac(sell.sales_tax_pct) or Fraction(0)) + (_frac(sell.broker_fee_pct) or Fraction(0))) / 100
    freight = _frac(sell.freight_per_unit) or Fraction(0)
    unit_sell = gross * (1 - fee) - freight
    revenue = unit_sell * qty
    profit = revenue - total_cost
    roi = (profit / total_cost) if total_cost else Fraction(0)

    total_time_s = int(schedule["total_time_s"])
    isk_per_hour = (profit * 3600 / total_time_s) if total_time_s else Fraction(0)
    slot_seconds = react_time_s + man_time_s
    isk_per_slot_hour = (profit * 3600 / slot_seconds) if slot_seconds else Fraction(0)

    return {
        "unit_make_cost": unit_cost, "total_make_cost": total_cost,
        "unit_sell": unit_sell, "revenue": revenue, "profit": profit, "roi": roi,
        "total_time_s": total_time_s, "react_time_s": react_time_s, "man_time_s": man_time_s,
        "isk_per_hour": isk_per_hour, "isk_per_slot_hour": isk_per_slot_hour,
        "runs_by_activity": runs_by_activity,
        "total_stages": int(schedule["total_stages"]),
        "peak_man": int(schedule["peak_man"]), "peak_react": int(schedule["peak_react"]),
    }


def compare_scratch_vs_bought(plan_scratch: ChainPlan, plan_bought: ChainPlan) -> ScratchDelta:
    """Delta between building a T2 component's reactions from zero vs buying the finished
    reaction intermediates — from two solved plans of the same target."""
    sc = plan_scratch.total_cost if plan_scratch.total_cost is not None else Fraction(0)
    bo = plan_bought.total_cost if plan_bought.total_cost is not None else Fraction(0)
    return ScratchDelta(cheaper="bought" if bo < sc else "scratch",
                        scratch_cost=sc, bought_cost=bo, delta=bo - sc)


def analyze_candidate(cand: Candidate, man_slots: int, react_slots: int) -> CandidateResult:
    """Solve one candidate from scratch, cost it, schedule it, and (for a T2 component
    with a ``bought`` variant) compare scratch vs bought. Pure."""
    plan = solve_chain(cand.scratch)
    m = _metrics_from_plan(plan, cand.sell, man_slots, react_slots)
    target_dec = plan.decisions.get(cand.type_id)

    svb: Optional[ScratchDelta] = None
    if cand.bought is not None:
        svb = compare_scratch_vs_bought(plan, solve_chain(cand.bought))

    return CandidateResult(
        type_id=cand.type_id, name=cand.name, target_qty=plan.target_qty,
        decision=target_dec.decision if target_dec else "unobtainable",
        blueprints=_aggregate_blueprints(plan), scratch_vs_bought=svb, **m,
    )


def analyze_candidates(cands: list[Candidate], man_slots: int, react_slots: int) -> list[CandidateResult]:
    """Analyse a batch, returned sorted by ROI (descending). The fast path is the native
    engine (see ``app.adapters.reaction_planner_engine``); this is the oracle/fallback."""
    out = [analyze_candidate(c, man_slots, react_slots) for c in cands]
    out.sort(key=lambda r: r.roi, reverse=True)
    return out


def batch_components(result: CandidateResult, lo: int = BATCH_LO, hi: int = BATCH_HI) -> CandidateResult:
    """Mark each made *component* (intermediate manufacturing node, i.e. not the target
    and not a reaction) with a recommended per-job batch clamped to ``[lo, hi]`` and the
    number of such batches. Presentation only — does not change any cost. Mutates and
    returns ``result`` (kept out of the engine/oracle parity surface so both feed it)."""
    for b in result.blueprints:
        is_component = b.activity == MANUFACTURING and b.type_id != result.type_id
        b.is_component = is_component
        if is_component and b.runs > 0:
            b.batch_size = min(hi, max(lo, b.runs)) if b.runs >= lo else b.runs
            b.batches = -(-b.runs // b.batch_size)  # ceil
    return result


# ── JSON seam (engine ⇄ oracle) ──────────────────────────────────────────────

def to_request_dict(cands: list[Candidate], man_slots: int, react_slots: int) -> dict:
    """Serialise a planner request for the native engine. Reuses the chain JSON seam
    for each candidate's ChainRequest(s)."""
    def cand_d(c: Candidate) -> dict:
        d = {
            "type_id": c.type_id, "name": c.name,
            "sell": {
                "unit_price": c.sell.unit_price, "sales_tax_pct": c.sell.sales_tax_pct,
                "broker_fee_pct": c.sell.broker_fee_pct, "freight_per_unit": c.sell.freight_per_unit,
            },
            "scratch": _chain_to_request_dict(c.scratch),
            "bought": _chain_to_request_dict(c.bought) if c.bought is not None else None,
        }
        return d

    return {"man_slots": man_slots, "react_slots": react_slots,
            "candidates": [cand_d(c) for c in cands]}


def _rat(x):
    """Parse an exact rational carried as ``[numerator, denominator]`` (or a number/null)."""
    if x is None:
        return None
    if isinstance(x, (list, tuple)):
        return Fraction(int(x[0]), int(x[1]))
    return Fraction(x)


def _result_from_dict(d: dict) -> CandidateResult:
    svb = None
    if d.get("scratch_vs_bought") is not None:
        s = d["scratch_vs_bought"]
        svb = ScratchDelta(cheaper=s["cheaper"], scratch_cost=_rat(s["scratch_cost"]),
                           bought_cost=_rat(s["bought_cost"]), delta=_rat(s["delta"]))
    blueprints = [
        BlueprintLine(type_id=b["type_id"], name=b["name"], activity=b["activity"],
                      runs=b["runs"], jobs=b["jobs"], qty_out=b["qty_out"])
        for b in d["blueprints"]
    ]
    return CandidateResult(
        type_id=d["type_id"], name=d["name"], target_qty=d["target_qty"],
        decision=d["decision"],
        unit_make_cost=_rat(d["unit_make_cost"]), total_make_cost=_rat(d["total_make_cost"]),
        unit_sell=_rat(d["unit_sell"]), revenue=_rat(d["revenue"]), profit=_rat(d["profit"]),
        roi=_rat(d["roi"]), total_time_s=d["total_time_s"],
        react_time_s=d["react_time_s"], man_time_s=d["man_time_s"],
        isk_per_hour=_rat(d["isk_per_hour"]), isk_per_slot_hour=_rat(d["isk_per_slot_hour"]),
        runs_by_activity={int(k): v for k, v in d["runs_by_activity"].items()},
        total_stages=d["total_stages"], peak_man=d["peak_man"], peak_react=d["peak_react"],
        blueprints=blueprints, scratch_vs_bought=svb,
    )


def results_from_dict(d: dict) -> list[CandidateResult]:
    return [_result_from_dict(c) for c in d["candidates"]]
