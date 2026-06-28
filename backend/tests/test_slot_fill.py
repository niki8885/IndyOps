"""
Reaction Planner slot-fill optimiser: fills N mfg + M reaction slots with the highest
ISK/hour batches without exceeding either pool. Mirrors tests/test_assignment.py.
"""
import pytest

pytest.importorskip("ortools")

from app.services.slot_fill import SlotCandidate, fill_slots

HOUR = 3600


def test_picks_higher_profit_per_reaction_second():
    # Both pure-reaction batches compete for one reaction slot-hour. A yields 1000 for the
    # full hour; two B's fit the hour but only yield 800 → A wins.
    a = SlotCandidate(1, "A", react_time_s=HOUR, man_time_s=0, profit=1000.0)
    b = SlotCandidate(2, "B", react_time_s=HOUR // 2, man_time_s=0, profit=400.0)
    res = fill_slots([a, b], man_slots=0, react_slots=1, horizon_s=HOUR)
    assert res.status in ("optimal", "feasible")
    picks = {p.type_id: p for p in res.chosen}
    assert picks[1].count == 1 and 2 not in picks
    assert res.total_profit == pytest.approx(1000.0)
    assert res.react_seconds_used == HOUR and res.man_seconds_used == 0


def test_respects_both_slot_pools():
    # C uses both a reaction and a manufacturing slot per batch; 1 slot each over 1h → 3 fit.
    c = SlotCandidate(3, "C", react_time_s=1000, man_time_s=1000, profit=500.0)
    res = fill_slots([c], man_slots=1, react_slots=1, horizon_s=HOUR)
    pick = next(p for p in res.chosen if p.type_id == 3)
    assert pick.count == 3                                   # min(3600//1000) on both pools
    assert res.react_seconds_used == 3000 and res.man_seconds_used == 3000
    assert res.total_profit == pytest.approx(1500.0)


def test_scales_to_more_slots():
    # Doubling reaction slots doubles the reaction-time budget → twice as many batches.
    c = SlotCandidate(3, "C", react_time_s=1200, man_time_s=0, profit=100.0)
    one = fill_slots([c], man_slots=0, react_slots=1, horizon_s=HOUR)
    two = fill_slots([c], man_slots=0, react_slots=2, horizon_s=HOUR)
    n1 = next(p for p in one.chosen if p.type_id == 3).count
    n2 = next(p for p in two.chosen if p.type_id == 3).count
    assert n2 == 2 * n1


def test_candidate_needing_missing_activity_cannot_run():
    # A manufacturing batch with zero reaction slots AND zero man slots can't be scheduled.
    d = SlotCandidate(4, "D", react_time_s=0, man_time_s=1000, profit=500.0)
    res = fill_slots([d], man_slots=0, react_slots=1, horizon_s=HOUR)
    assert res.status == "empty" and not res.chosen


def test_unprofitable_candidate_skipped():
    loss = SlotCandidate(5, "Loss", react_time_s=1000, man_time_s=0, profit=-50.0)
    res = fill_slots([loss], man_slots=0, react_slots=1, horizon_s=HOUR)
    assert res.status == "empty" and not res.chosen


def test_total_isk_per_hour_is_profit_over_horizon():
    c = SlotCandidate(6, "C", react_time_s=HOUR, man_time_s=0, profit=2000.0)
    res = fill_slots([c], man_slots=0, react_slots=2, horizon_s=2 * HOUR)
    # 2 react slots × 2h = 4 react-hours; each batch is 1h → 4 batches × 2000 = 8000 over 2h.
    assert res.total_profit == pytest.approx(8000.0)
    assert res.total_isk_per_hour == pytest.approx(4000.0)
