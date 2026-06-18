"""FIFO consumption planner — concrete cases (invariants are in test_properties)."""
import pytest
from app.services.costing import plan_fifo


def test_partial_second_lot():
    # take 10 from lot0 then 20 from lot1; lot2 untouched
    plan = plan_fifo([(10, 5.0), (40, 6.0), (25, None)], 30)
    assert plan.consumed == 30
    assert plan.cost == 10 * 5.0 + 20 * 6.0          # 170.0
    assert [(line.index, line.take) for line in plan.lines] == [(0, 10), (1, 20)]


def test_shortfall_consumes_all_available():
    plan = plan_fifo([(5, 2.0)], 100)
    assert plan.consumed == 5
    assert plan.cost == pytest.approx(10.0)


def test_none_price_counts_as_zero():
    plan = plan_fifo([(10, None)], 10)
    assert plan.consumed == 10
    assert plan.cost == 0


def test_zero_need_consumes_nothing():
    plan = plan_fifo([(10, 5.0)], 0)
    assert plan.consumed == 0 and plan.cost == 0 and plan.lines == []
