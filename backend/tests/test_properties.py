"""
Property-based invariants (hypothesis). These hold for *any* valid input, so
they catch edge cases the golden tests don't enumerate.
"""
from dataclasses import asdict

import pytest
from hypothesis import given, strategies as st

from app.services.allocation import Venue, allocate
from app.services.costing import plan_fifo
from app.services.manufacturing import CalcInput, Material, adj_qty, run_calculation


# ── adj_qty is never below `runs` (you can't make fewer than one job's worth) ──
@given(
    base_qty=st.integers(min_value=0, max_value=10_000),
    runs=st.integers(min_value=1, max_value=1_000),
    me=st.integers(min_value=0, max_value=90),
    mult=st.floats(min_value=0.01, max_value=2.0, allow_nan=False, allow_infinity=False),
)
def test_adj_qty_at_least_runs(base_qty, runs, me, mult):
    assert adj_qty(base_qty, runs, me, mult) >= runs


# ── FIFO: cost == Σ(take × price); consumed == min(need, available) ──
_lots = st.lists(
    st.tuples(
        st.integers(min_value=1, max_value=1_000),
        st.one_of(st.none(),
                  st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False)),
    ),
    min_size=0, max_size=30,
)


@given(lots=_lots, need=st.integers(min_value=0, max_value=20_000))
def test_fifo_cost_and_consumed(lots, need):
    plan = plan_fifo(lots, need)
    available = sum(q for q, _ in lots)
    assert plan.consumed == min(need, available)
    assert sum(line.take for line in plan.lines) == plan.consumed
    # Σ(take × price) — approx because float summation order differs by an ULP.
    expected_cost = sum(line.take * (lots[line.index][1] or 0) for line in plan.lines)
    assert plan.cost == pytest.approx(expected_cost, rel=1e-9, abs=1e-6)


# ── profit is monotonic non-decreasing in output_price ──
@given(
    p1=st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False),
    dp=st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False),
    runs=st.integers(min_value=1, max_value=50),
    broker=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
)
def test_profit_monotonic_in_price(p1, dp, runs, broker):
    def profit(price):
        return run_calculation(CalcInput(
            product_name="X", product_qty_per_run=1, runs=runs, me=0, te=0, base_time_per_run=1,
            materials=[Material(34, "T", 100, 5.0)], output_price=price, bpc_cost=0.0,
            broker_fee_pct=broker, system_cost_index=0.0, facility_tax_pct=0.0,
        )).results.profit

    assert profit(p1 + dp) >= profit(p1)


# ── stacking ME/TE multipliers commute: swapping rig↔role changes nothing ──
@given(
    a=st.floats(min_value=0, max_value=90, allow_nan=False, allow_infinity=False),
    b=st.floats(min_value=0, max_value=90, allow_nan=False, allow_infinity=False),
    runs=st.integers(min_value=1, max_value=50),
)
def test_multiplier_permutation_invariance(a, b, runs):
    def calc(mb, mr, tb, tr):
        return asdict(run_calculation(CalcInput(
            product_name="X", product_qty_per_run=1, runs=runs, me=5, te=5, base_time_per_run=600,
            materials=[Material(34, "T", 137, 7.0)], output_price=1000.0, bpc_cost=0.0,
            broker_fee_pct=0.0, system_cost_index=0.0, facility_tax_pct=0.0,
            material_bonus_pct=mb, material_role_pct=mr, time_bonus_pct=tb, time_role_pct=tr,
        )))

    assert calc(a, b, a, b) == calc(b, a, b, a)


# ── allocation conserves quantity when every venue is fully priced ──
_venues = st.lists(
    st.tuples(
        st.floats(min_value=0.1, max_value=1e6, allow_nan=False, allow_infinity=False),  # net_instant
        st.floats(min_value=0.1, max_value=1e6, allow_nan=False, allow_infinity=False),  # net_patient
        st.floats(min_value=0, max_value=500, allow_nan=False, allow_infinity=False),    # hist_vol
    ),
    min_size=1, max_size=8,
)


@given(
    rows=_venues,
    qty=st.integers(min_value=1, max_value=100_000),
    strategy=st.sampled_from(["fast", "balanced", "maxprofit"]),
    balance_days=st.integers(min_value=1, max_value=30),
)
def test_allocations_sum_to_qty(rows, qty, strategy, balance_days):
    venues = [Venue(i, f"v{i}", inst, pat, vol) for i, (inst, pat, vol) in enumerate(rows)]
    allocs = allocate(venues, qty, strategy, balance_days)
    assert sum(a.qty for a in allocs) == qty
