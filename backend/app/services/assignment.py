from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from app.services.chain import PlannedJob


# ── inputs ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Line:
    """Parallel industry lines available for one (place, slot_kind) this window."""
    place_id: int
    slot_kind: str
    count: int
    max_jobs: Optional[int] = None


@dataclass
class SlotConfig:
    horizon_s: int
    lines: list[Line] = field(default_factory=list)

    def for_group(self, place_id: int, slot_kind: str) -> Optional[Line]:
        for ln in self.lines:
            if ln.place_id == place_id and ln.slot_kind == slot_kind:
                return ln
        return None


# outputs

@dataclass
class JobAssignment:
    job_index: int
    type_id: int
    name: str
    place_id: int
    place_name: str
    slot_kind: str
    in_house: bool
    time_s: int
    cost: float


@dataclass
class LineUsage:
    place_id: int
    slot_kind: str
    lines: int
    capacity_s: int
    used_s: int
    jobs: int
    forced_s: int


@dataclass
class AssignmentResult:
    status: str
    in_house: list[JobAssignment]
    bought: list[JobAssignment]
    total_cost: float
    savings_captured: float
    savings_forfeited: float
    usage: list[LineUsage]
    note: str = ""


def _savings(job: PlannedJob) -> float:
    fb = job.buy_fallback_total
    return round((fb - job.make_cost), 2) if fb is not None else 0.0


def assign_jobs(jobs: list[PlannedJob], cfg: SlotConfig) -> AssignmentResult:
    """Pick the in-house subset that fits the window and maximises savings."""
    if not jobs:
        return AssignmentResult("empty", [], [], 0.0, 0.0, 0.0, [], "no jobs")

    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:
        raise RuntimeError(
            "ortools is required for slot assignment (pip install ortools)"
        ) from exc

    groups: dict[tuple[int, str], list[int]] = defaultdict(list)
    for i, j in enumerate(jobs):
        groups[(j.place_id, j.slot_kind)].append(i)

    model = cp_model.CpModel()
    x = [model.NewBoolVar(f"x{i}") for i in range(len(jobs))]
    for i, j in enumerate(jobs):
        if not j.bounceable:
            model.Add(x[i] == 1)

    for (place_id, kind), idxs in groups.items():
        ln = cfg.for_group(place_id, kind)
        lines = ln.count if ln else 0
        capacity = lines * cfg.horizon_s
        model.Add(sum(jobs[i].time_s * x[i] for i in idxs) <= capacity)
        if ln and ln.max_jobs is not None:
            model.Add(sum(x[i] for i in idxs) <= ln.max_jobs)

    model.Maximize(sum(int(round(_savings(jobs[i]))) * x[i] for i in range(len(jobs))))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return _infeasible_report(jobs, cfg, groups)

    in_house: list[JobAssignment] = []
    bought: list[JobAssignment] = []
    captured = forfeited = 0.0
    used: dict[tuple[int, str], list[int]] = defaultdict(list)

    for i, j in enumerate(jobs):
        run = solver.Value(x[i]) == 1
        cost = j.make_cost if run else (j.buy_fallback_total or 0.0)
        ja = JobAssignment(i, j.type_id, j.name, j.place_id, j.place_name, j.slot_kind, run, j.time_s, round(cost, 2))
        if run:
            in_house.append(ja)
            used[(j.place_id, j.slot_kind)].append(i)
            captured += _savings(j) if j.bounceable else 0.0
        else:
            bought.append(ja)
            forfeited += _savings(j)

    usage = []
    for (place_id, kind), idxs in groups.items():
        ln = cfg.for_group(place_id, kind)
        lines = ln.count if ln else 0
        run_idxs = used.get((place_id, kind), [])
        forced_s = sum(jobs[i].time_s for i in idxs if not jobs[i].bounceable)
        usage.append(LineUsage(
            place_id=place_id, slot_kind=kind, lines=lines,
            capacity_s=lines * cfg.horizon_s,
            used_s=sum(jobs[i].time_s for i in run_idxs),
            jobs=len(run_idxs), forced_s=forced_s,
        ))

    total_cost = round(sum(a.cost for a in in_house) + sum(a.cost for a in bought), 2)
    return AssignmentResult(
        status="optimal" if status == cp_model.OPTIMAL else "feasible",
        in_house=in_house, bought=bought,
        total_cost=total_cost,
        savings_captured=round(captured, 2),
        savings_forfeited=round(forfeited, 2),
        usage=usage,
    )


def _infeasible_report(jobs, cfg: SlotConfig, groups) -> AssignmentResult:
    """Forced (non-bounceable) jobs alone exceed capacity somewhere — say where."""
    overflow = []
    usage = []
    for (place_id, kind), idxs in groups.items():
        ln = cfg.for_group(place_id, kind)
        lines = ln.count if ln else 0
        cap = lines * cfg.horizon_s
        forced_s = sum(jobs[i].time_s for i in idxs if not jobs[i].bounceable)
        usage.append(LineUsage(place_id, kind, lines, cap, forced_s, 0, forced_s))
        if forced_s > cap:
            overflow.append(f"{kind}@{place_id}: forced {forced_s}s > capacity {cap}s")
    note = "infeasible: " + ("; ".join(overflow) if overflow
                             else "no capacity configured for some jobs")
    return AssignmentResult("infeasible", [], [], 0.0, 0.0, 0.0, usage, note)


# ── multi-location placement ─────────────────────────────────────────────────
# Same window/slot model, but each job may run at one of several eligible
# structures (the "where" the core left open). OR-Tools picks the structure per
# job under each structure's slot capacity. Material quantities (and so the BOM
# flow) come from the core's reference location — here we only optimise install
# cost, job time and slot placement across structures, plus the tip buy-fallback.

@dataclass(frozen=True)
class Placement:
    """One structure a job can run at, with its cost/time there."""
    place_id: int
    place_name: str
    slot_kind: str
    cost: float        # full in-house cost at this structure (install + bpc + leaf material)
    time_s: int


@dataclass
class MultiJob:
    index: int
    type_id: int
    name: str
    slot_kind: str
    bounceable: bool
    buy_fallback_total: Optional[float]
    placements: list[Placement]


def assign_multi(jobs: list[MultiJob], cfg: SlotConfig) -> AssignmentResult:
    """Assign jobs to structures (and in-house vs buy) minimising total cost."""
    if not jobs:
        return AssignmentResult("empty", [], [], 0.0, 0.0, 0.0, [], "no jobs")

    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:  # pragma: no cover - dep guard
        raise RuntimeError("ortools is required for slot assignment (pip install ortools)") from exc

    model = cp_model.CpModel()
    x = {j.index: model.NewBoolVar(f"x{j.index}") for j in jobs}
    y: dict[tuple[int, int], object] = {}
    for j in jobs:
        yvars = []
        for pi in range(len(j.placements)):
            v = model.NewBoolVar(f"y{j.index}_{pi}")
            y[(j.index, pi)] = v
            yvars.append(v)
        model.Add(sum(yvars) == x[j.index]) if yvars else model.Add(x[j.index] == 0)
        if not j.bounceable:
            model.Add(x[j.index] == 1)   # mid-tree / unbuyable must run somewhere

    cap_terms: dict[tuple[int, str], list] = defaultdict(list)
    for j in jobs:
        for pi, pl in enumerate(j.placements):
            cap_terms[(pl.place_id, pl.slot_kind)].append((pl.time_s, y[(j.index, pi)]))
    for (place_id, kind), terms in cap_terms.items():
        ln = cfg.for_group(place_id, kind)
        lines = ln.count if ln else 0
        model.Add(sum(t * v for t, v in terms) <= lines * cfg.horizon_s)
        if ln and ln.max_jobs is not None:
            model.Add(sum(v for _, v in terms) <= ln.max_jobs)

    obj = []
    for j in jobs:
        for pi, pl in enumerate(j.placements):
            obj.append(int(round(pl.cost)) * y[(j.index, pi)])
        if j.buy_fallback_total is not None:
            obj.append(int(round(j.buy_fallback_total)) * (1 - x[j.index]))
    model.Minimize(sum(obj))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return _infeasible_multi(jobs, cfg)

    in_house: list[JobAssignment] = []
    bought: list[JobAssignment] = []
    captured = forfeited = 0.0
    used: dict[tuple[int, str], list[int]] = defaultdict(list)

    for j in jobs:
        if solver.Value(x[j.index]) == 1:
            pi = next(p for p in range(len(j.placements)) if solver.Value(y[(j.index, p)]) == 1)
            pl = j.placements[pi]
            in_house.append(JobAssignment(j.index, j.type_id, j.name, pl.place_id, pl.place_name, pl.slot_kind,
                                          True, pl.time_s, round(pl.cost, 2)))
            used[(pl.place_id, pl.slot_kind)].append(pl.time_s)
            if j.buy_fallback_total is not None:
                captured += j.buy_fallback_total - pl.cost
        else:
            fb = j.buy_fallback_total or 0.0
            bought.append(JobAssignment(j.index, j.type_id, j.name, 0, "", j.slot_kind, False, 0, round(fb, 2)))
            if j.buy_fallback_total is not None and j.placements:
                forfeited += j.buy_fallback_total - min(pl.cost for pl in j.placements)

    usage = []
    for (place_id, kind) in cap_terms:
        ln = cfg.for_group(place_id, kind)
        lines = ln.count if ln else 0
        run_times = used.get((place_id, kind), [])
        usage.append(LineUsage(place_id, kind, lines, lines * cfg.horizon_s,
                               sum(run_times), len(run_times), 0))

    total_cost = round(sum(a.cost for a in in_house) + sum(a.cost for a in bought), 2)
    return AssignmentResult(
        status="optimal" if status == cp_model.OPTIMAL else "feasible",
        in_house=in_house, bought=bought, total_cost=total_cost,
        savings_captured=round(captured, 2), savings_forfeited=round(forfeited, 2),
        usage=usage,
    )


def _infeasible_multi(jobs: list[MultiJob], cfg: SlotConfig) -> AssignmentResult:
    seen: set[tuple[int, str]] = set()
    usage = []
    for j in jobs:
        for pl in j.placements:
            key = (pl.place_id, pl.slot_kind)
            if key in seen:
                continue
            seen.add(key)
            ln = cfg.for_group(*key)
            lines = ln.count if ln else 0
            usage.append(LineUsage(pl.place_id, pl.slot_kind, lines, lines * cfg.horizon_s, 0, 0, 0))
    forced = sum(1 for j in jobs if not j.bounceable)
    note = (f"infeasible: {forced} forced in-house job(s) cannot be placed within "
            "the configured structures/slots/window")
    return AssignmentResult("infeasible", [], [], 0.0, 0.0, 0.0, usage, note)
