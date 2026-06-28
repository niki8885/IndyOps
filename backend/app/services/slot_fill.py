"""
Reaction Planner slot-fill optimiser — "so the slots don't sit idle".

Given the analysed candidates (each a *batch* that consumes some reaction-slot time and
some manufacturing-slot time and yields a known profit) and the available N manufacturing
+ M reaction slots over a planning horizon, pick how many batches of each candidate to run
so total ISK/hour is maximised without exceeding either slot pool. Maximising profit over a
fixed horizon *is* maximising ISK/hour.

This is a 2-resource unbounded integer knapsack — a different problem from
``services.assignment`` (which assigns one product's jobs to structures maximising savings),
so it is a sibling, not a change to that module. Pure; OR-Tools is imported lazily and
guarded exactly like ``assignment.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SlotCandidate:
    """One candidate batch competing for slots. ``react_time_s``/``man_time_s`` are the
    reaction- and manufacturing-slot seconds one batch consumes; ``profit`` is its net
    profit (per batch)."""
    type_id: int
    name: str
    react_time_s: int
    man_time_s: int
    profit: float
    isk_per_hour: float = 0.0
    max_count: Optional[int] = None   # optional hard cap on repeats (else bounded by capacity)


@dataclass
class SlotPick:
    type_id: int
    name: str
    count: int
    react_seconds: int
    man_seconds: int
    profit: float
    isk_per_hour: float


@dataclass
class SlotFillResult:
    status: str
    chosen: list[SlotPick] = field(default_factory=list)
    total_profit: float = 0.0
    total_isk_per_hour: float = 0.0
    react_seconds_used: int = 0
    man_seconds_used: int = 0
    react_capacity_s: int = 0
    man_capacity_s: int = 0
    note: str = ""

    @property
    def react_util(self) -> float:
        return self.react_seconds_used / self.react_capacity_s if self.react_capacity_s else 0.0

    @property
    def man_util(self) -> float:
        return self.man_seconds_used / self.man_capacity_s if self.man_capacity_s else 0.0


def _upper_bound(c: SlotCandidate, react_cap: int, man_cap: int) -> int:
    """How many batches could *possibly* fit given each resource — bounds the int var."""
    bounds = []
    if c.react_time_s > 0:
        bounds.append(react_cap // c.react_time_s)
    if c.man_time_s > 0:
        bounds.append(man_cap // c.man_time_s)
    ub = min(bounds) if bounds else 0       # no slot-time at all → can't schedule it
    if c.max_count is not None:
        ub = min(ub, c.max_count)
    return max(0, ub)


def fill_slots(cands: list[SlotCandidate], man_slots: int, react_slots: int,
               horizon_s: int) -> SlotFillResult:
    """Pick the batch counts that fill ``man_slots`` mfg + ``react_slots`` reaction slots
    over ``horizon_s`` seconds to maximise ISK/hour (= profit over the horizon)."""
    react_cap = max(0, react_slots) * max(0, horizon_s)
    man_cap = max(0, man_slots) * max(0, horizon_s)
    horizon_h = horizon_s / 3600.0 if horizon_s > 0 else 0.0

    # Only candidates that are profitable and can actually be scheduled are worth modelling.
    pool = [c for c in cands if c.profit > 0 and _upper_bound(c, react_cap, man_cap) > 0]
    if not pool:
        return SlotFillResult("empty", react_capacity_s=react_cap, man_capacity_s=man_cap,
                              note="no profitable candidate fits the available slots")

    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:  # pragma: no cover - dep guard
        raise RuntimeError("ortools is required for slot fill (pip install ortools)") from exc

    model = cp_model.CpModel()
    counts = {c.type_id: model.NewIntVar(0, _upper_bound(c, react_cap, man_cap), f"n{c.type_id}")
              for c in pool}

    model.Add(sum(c.react_time_s * counts[c.type_id] for c in pool) <= react_cap)
    model.Add(sum(c.man_time_s * counts[c.type_id] for c in pool) <= man_cap)
    model.Maximize(sum(int(round(c.profit)) * counts[c.type_id] for c in pool))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return SlotFillResult("infeasible", react_capacity_s=react_cap, man_capacity_s=man_cap,
                              note="optimiser found no feasible slot fill")

    chosen: list[SlotPick] = []
    react_used = man_used = 0
    total_profit = 0.0
    for c in pool:
        n = int(solver.Value(counts[c.type_id]))
        if n <= 0:
            continue
        chosen.append(SlotPick(
            type_id=c.type_id, name=c.name, count=n,
            react_seconds=c.react_time_s * n, man_seconds=c.man_time_s * n,
            profit=round(c.profit * n, 2), isk_per_hour=round(c.isk_per_hour, 2)))
        react_used += c.react_time_s * n
        man_used += c.man_time_s * n
        total_profit += c.profit * n

    chosen.sort(key=lambda p: p.profit, reverse=True)
    return SlotFillResult(
        status="optimal" if status == cp_model.OPTIMAL else "feasible",
        chosen=chosen, total_profit=round(total_profit, 2),
        total_isk_per_hour=round(total_profit / horizon_h, 2) if horizon_h else 0.0,
        react_seconds_used=react_used, man_seconds_used=man_used,
        react_capacity_s=react_cap, man_capacity_s=man_cap,
    )
