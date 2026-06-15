"""
OR-Tools slot assignment tests. Build PlannedJobs directly with known
time/savings so the CP-SAT choices are hand-predictable.
"""
import pytest

from app.services.assignment import Line, MultiJob, Placement, SlotConfig, assign_jobs, assign_multi
from app.services.chain import PlannedJob

pytest.importorskip("ortools")


def _job(tid, time_s, make_cost, savings, *, place=1, kind="manufacturing", bounceable=True):
    """A 1-unit job whose buy_fallback_total − make_cost == savings."""
    fb_unit = (make_cost + savings) if bounceable else None
    return PlannedJob(
        type_id=tid, name=f"J{tid}", activity=1, place_id=place, place_name="P",
        slot_kind=kind, runs=1, qty_out=1, time_s=time_s,
        install_cost=make_cost, bpc_cost=0.0, leaf_material_cost=0.0, inputs=[],
        buy_fallback_unit=fb_unit, bounceable=bounceable,
    )


def test_empty():
    r = assign_jobs([], SlotConfig(horizon_s=3600))
    assert r.status == "empty"


def test_unlimited_slots_all_in_house():
    jobs = [_job(1, 100, 500, 50), _job(2, 100, 500, 30)]
    cfg = SlotConfig(horizon_s=10_000, lines=[Line(1, "manufacturing", 10)])
    r = assign_jobs(jobs, cfg)
    assert r.status in ("optimal", "feasible")
    assert len(r.in_house) == 2 and not r.bought
    assert r.savings_forfeited == 0.0


def test_tight_slots_keep_higher_savings():
    # capacity = 1 line × 100s = 100s. Each job is 100s → only one fits.
    # keep the higher-savings job (50) in-house, bounce the other (30).
    jobs = [_job(1, 100, 500, 50), _job(2, 100, 500, 30)]
    cfg = SlotConfig(horizon_s=100, lines=[Line(1, "manufacturing", 1)])
    r = assign_jobs(jobs, cfg)
    assert [a.type_id for a in r.in_house] == [1]
    assert [a.type_id for a in r.bought] == [2]
    assert r.savings_captured == 50.0
    assert r.savings_forfeited == 30.0


def test_forced_job_over_capacity_is_infeasible():
    # non-bounceable (mid-tree) job needs 200s but only 100s of capacity exists.
    jobs = [_job(1, 200, 500, 0, bounceable=False)]
    cfg = SlotConfig(horizon_s=100, lines=[Line(1, "manufacturing", 1)])
    r = assign_jobs(jobs, cfg)
    assert r.status == "infeasible"
    assert "forced" in r.note


def test_non_bounceable_runs_even_with_tiny_savings():
    # a forced job and a bounceable one compete; forced always stays in-house.
    jobs = [_job(1, 100, 500, 0, bounceable=False), _job(2, 100, 500, 999)]
    cfg = SlotConfig(horizon_s=100, lines=[Line(1, "manufacturing", 1)])
    r = assign_jobs(jobs, cfg)
    assert 1 in [a.type_id for a in r.in_house]      # forced kept
    assert 2 in [a.type_id for a in r.bought]        # high-savings one bounced (no room)


def test_separate_lines_per_slot_kind():
    # manufacturing and reaction lines are independent capacity pools.
    jobs = [
        _job(1, 100, 500, 40, kind="manufacturing"),
        _job(2, 100, 500, 40, kind="reaction"),
    ]
    cfg = SlotConfig(horizon_s=100, lines=[
        Line(1, "manufacturing", 1), Line(1, "reaction", 1),
    ])
    r = assign_jobs(jobs, cfg)
    assert len(r.in_house) == 2 and not r.bought     # each fits its own pool


def test_missing_capacity_bounces_bounceable():
    # no lines configured for the job's pool → must bounce (it's bounceable).
    jobs = [_job(1, 100, 500, 40)]
    cfg = SlotConfig(horizon_s=100, lines=[])
    r = assign_jobs(jobs, cfg)
    assert r.status in ("optimal", "feasible")
    assert [a.type_id for a in r.bought] == [1]


# ── multi-location placement (assign_multi) ──────────────────────────────────

def _pl(place, cost, time_s, kind="manufacturing"):
    return Placement(place, f"S{place}", kind, cost, time_s)


def test_multi_empty():
    assert assign_multi([], SlotConfig(3600)).status == "empty"


def test_multi_prefers_cheaper_structure():
    jobs = [MultiJob(0, 1, "J", "manufacturing", True, 1000.0, [_pl(1, 500, 50), _pl(2, 600, 50)])]
    cfg = SlotConfig(1000, [Line(1, "manufacturing", 1), Line(2, "manufacturing", 1)])
    r = assign_multi(jobs, cfg)
    assert [a.place_id for a in r.in_house] == [1]   # cheaper structure chosen


def test_multi_splits_across_structures():
    # two 100s jobs, each structure 1 line × 100s. Only by using both structures
    # do both fit in-house.
    jobs = [
        MultiJob(0, 1, "A", "manufacturing", True, 9999.0, [_pl(1, 500, 100), _pl(2, 500, 100)]),
        MultiJob(1, 2, "B", "manufacturing", True, 9999.0, [_pl(1, 500, 100), _pl(2, 500, 100)]),
    ]
    cfg = SlotConfig(100, [Line(1, "manufacturing", 1), Line(2, "manufacturing", 1)])
    r = assign_multi(jobs, cfg)
    assert len(r.in_house) == 2 and not r.bought
    assert {a.place_id for a in r.in_house} == {1, 2}


def test_multi_bounces_when_no_structure_fits():
    # both jobs only eligible at structure 1 (1 line × 100s) → one bounces to buy.
    jobs = [
        MultiJob(0, 1, "A", "manufacturing", True, 9999.0, [_pl(1, 500, 100)]),
        MultiJob(1, 2, "B", "manufacturing", True, 9999.0, [_pl(1, 500, 100)]),
    ]
    cfg = SlotConfig(100, [Line(1, "manufacturing", 1)])
    r = assign_multi(jobs, cfg)
    assert len(r.in_house) == 1 and len(r.bought) == 1


def test_multi_forced_job_infeasible():
    jobs = [MultiJob(0, 1, "A", "manufacturing", False, None, [_pl(1, 500, 200), _pl(2, 500, 200)])]
    cfg = SlotConfig(100, [Line(1, "manufacturing", 1), Line(2, "manufacturing", 1)])
    r = assign_multi(jobs, cfg)
    assert r.status == "infeasible"


def test_multi_reaction_and_manufacturing_pools_independent():
    jobs = [
        MultiJob(0, 1, "M", "manufacturing", True, 9999.0, [_pl(1, 500, 100, "manufacturing")]),
        MultiJob(1, 2, "R", "reaction", True, 9999.0, [_pl(1, 500, 100, "reaction")]),
    ]
    cfg = SlotConfig(100, [Line(1, "manufacturing", 1), Line(1, "reaction", 1)])
    r = assign_multi(jobs, cfg)
    assert len(r.in_house) == 2 and not r.bought
