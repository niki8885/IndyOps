from __future__ import annotations
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from app.services.ore_acquisition import Need


@dataclass(frozen=True)
class BuyOption:
    key: str
    kind: str
    type_id: int
    name: str
    source: str
    cost_per_unit: float
    yields: dict[int, float]


@dataclass
class BasketBuy:
    kind: str
    type_id: int
    name: str
    source: str
    units: int
    unit_cost: float
    total_cost: float


@dataclass
class MineralCoverage:
    type_id: int
    name: str
    needed: float
    produced: float
    surplus: float


@dataclass
class BasketPlan:
    status: str
    total_cost: Optional[float]
    buys: list[BasketBuy] = field(default_factory=list)
    coverage: list[MineralCoverage] = field(default_factory=list)
    uncoverable: list[str] = field(default_factory=list)
    note: str = ""


def optimize_basket(needs: list[Need], options: list[BuyOption],
                    integer: bool = False, max_seconds: float = 10.0) -> BasketPlan:
    """Cheapest set of buys covering every needed mineral (quantities required)."""
    wanted = [n for n in needs if n.qty and n.qty > 0]
    if not wanted:
        return BasketPlan(status="empty", total_cost=None,
                          note="basket optimisation needs target quantities")

    producible: set[int] = set()
    for o in options:
        producible.update(m for m, q in o.yields.items() if q > 0)
    coverable = [n for n in wanted if n.type_id in producible]
    uncoverable = [n.name for n in wanted if n.type_id not in producible]
    if not coverable:
        return BasketPlan(status="infeasible", total_cost=None, uncoverable=uncoverable,
                          note="no source/ore can supply the requested minerals")

    try:
        from ortools.linear_solver import pywraplp
    except ImportError as exc:
        raise RuntimeError("ortools is required for basket optimisation (pip install ortools)") from exc

    solver = pywraplp.Solver.CreateSolver("CBC" if integer else "GLOP")
    if solver is None:
        raise RuntimeError("OR-Tools solver unavailable")

    inf = solver.infinity()
    u = {o.key: (solver.IntVar(0, inf, o.key) if integer else solver.NumVar(0, inf, o.key))
         for o in options}

    for n in coverable:
        ct = solver.Constraint(float(n.qty), inf)
        for o in options:
            c = o.yields.get(n.type_id, 0.0)
            if c:
                ct.SetCoefficient(u[o.key], c)

    obj = solver.Objective()
    for o in options:
        obj.SetCoefficient(u[o.key], o.cost_per_unit)
    obj.SetMinimization()

    solver.set_time_limit(int(max_seconds * 1000))
    rc = solver.Solve()
    if rc not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return BasketPlan(status="infeasible", total_cost=None, uncoverable=uncoverable,
                          note="solver could not find a feasible plan")

    produced: dict[int, float] = defaultdict(float)
    buys: list[BasketBuy] = []
    opt_by_key = {o.key: o for o in options}
    for key, var in u.items():
        q = var.solution_value()
        if q <= 1e-6:
            continue
        o = opt_by_key[key]
        units = int(math.ceil(q - 1e-9))
        buys.append(BasketBuy(
            kind=o.kind, type_id=o.type_id, name=o.name, source=o.source,
            units=units, unit_cost=round(o.cost_per_unit, 2),
            total_cost=round(units * o.cost_per_unit, 2),
        ))
        for m, c in o.yields.items():
            produced[m] += units * c

    coverage = [
        MineralCoverage(
            type_id=n.type_id, name=n.name, needed=n.qty,
            produced=round(produced.get(n.type_id, 0.0), 2),
            surplus=round(produced.get(n.type_id, 0.0) - n.qty, 2),
        )
        for n in coverable
    ]
    buys.sort(key=lambda b: b.total_cost, reverse=True)
    return BasketPlan(
        status="optimal" if rc == pywraplp.Solver.OPTIMAL else "feasible",
        total_cost=round(sum(b.total_cost for b in buys), 2),
        buys=buys, coverage=coverage, uncoverable=uncoverable,
        note=("some requested minerals have no source — excluded" if uncoverable else ""),
    )
