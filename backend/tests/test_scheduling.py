"""
Stage scheduler goldens (IO-10): dependency-ordered waves capped by manufacturing /
reaction slots. Hand-computed stage layouts so a packing/ordering regression is caught.
"""
from dataclasses import dataclass, field

from app.services.scheduling import stage_schedule


@dataclass
class _Inp:
    type_id: int
    is_make: bool


@dataclass
class _Job:
    type_id: int
    slot_kind: str = "manufacturing"
    runs: int = 1
    time_s: int = 100
    name: str = "J"
    inputs: list = field(default_factory=list)


def _job(tid, kind="manufacturing", makes_from=(), time_s=100):
    return _Job(type_id=tid, slot_kind=kind, time_s=time_s,
                inputs=[_Inp(t, True) for t in makes_from])


def test_children_scheduled_before_parents():
    jobs = [_job(1, makes_from=[2]), _job(2)]      # W(1) consumes A(2)
    sch = stage_schedule(jobs, man_slots=10, react_slots=10)
    stage_of = {j["type_id"]: s["stage"] for s in sch["stages"] for j in s["jobs"]}
    assert stage_of[2] < stage_of[1] and sch["total_stages"] == 2


def test_slot_cap_splits_wide_tier_across_stages():
    jobs = [_job(t) for t in range(10, 15)]         # 5 independent manufacturing jobs
    sch = stage_schedule(jobs, man_slots=2, react_slots=2)
    assert sch["total_stages"] == 3
    assert [s["man_used"] for s in sch["stages"]] == [2, 2, 1]


def test_manufacturing_and_reaction_counted_separately():
    jobs = [_job(10), _job(11), _job(20, "reaction"), _job(21, "reaction")]
    sch = stage_schedule(jobs, man_slots=1, react_slots=1)
    assert sch["total_stages"] == 2
    assert all(s["man_used"] == 1 and s["react_used"] == 1 for s in sch["stages"])


def test_zero_slots_means_unlimited():
    jobs = [_job(t) for t in range(5)]
    sch = stage_schedule(jobs, man_slots=0, react_slots=0)
    assert sch["total_stages"] == 1 and sch["stages"][0]["man_used"] == 5


def test_cumulative_time_sums_stage_maxima():
    jobs = [_job(1, makes_from=[2], time_s=100), _job(2, time_s=300)]
    sch = stage_schedule(jobs, man_slots=10, react_slots=10)
    assert sch["stages"][0]["stage_time_s"] == 300   # A runs first
    assert sch["stages"][1]["stage_time_s"] == 100   # then W
    assert sch["total_time_s"] == 400
