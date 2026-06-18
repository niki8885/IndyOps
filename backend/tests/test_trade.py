"""Unit tests for the pure trade-preprocessing math (no DB / no I/O)."""
import pytest

from app.services import trade


def _hist(prices_volumes):
    return [{"average": p, "volume": v} for p, v in prices_volumes]


def test_daily_volume_mean():
    assert trade.daily_volume(_hist([(100, 10), (100, 20), (100, 30)])) == pytest.approx(20.0)
    assert trade.daily_volume([]) == pytest.approx(0.0)
    assert trade.daily_volume(None) == pytest.approx(0.0)


def test_volatility_cv():
    # flat prices → 0 variation
    assert trade.volatility_cv(_hist([(100, 1), (100, 1), (100, 1)])) == pytest.approx(0.0)
    # mean 100, population std 10 → CV 0.1
    assert trade.volatility_cv(_hist([(90, 1), (110, 1)])) == pytest.approx(0.1)
    # too few usable points → None
    assert trade.volatility_cv(_hist([(100, 1)])) is None
    assert trade.volatility_cv(None) is None


def test_transport_cost():
    assert trade.transport_cost_per_unit(2.0, 5, 1000) == pytest.approx(10000.0)
    assert trade.transport_cost_per_unit(2.0, 0, 1000) == pytest.approx(0.0)     # same hub
    assert trade.transport_cost_per_unit(-1, 5, 1000) == pytest.approx(0.0)      # clamps negatives


def test_patient_margin():
    r = trade.patient_margin(100, 150, broker_fee=0.03, sales_tax=0.045, transport_cost=5)
    # revenue 150*0.925=138.75, cost 105, profit 33.75, ROI 33.75/105
    assert r["profit_isk"] == pytest.approx(33.75)
    assert r["margin_pct"] == pytest.approx(33.75 / 105, abs=1e-6)


def test_instant_margin_lower_than_patient():
    patient = trade.patient_margin(100, 150, 0.03, 0.045, 5)
    instant = trade.instant_margin(100, 130, sales_tax=0.045, transport_cost=5)
    # selling into a lower buy order yields less profit than listing at the ask
    assert instant["profit_isk"] == pytest.approx(130 * 0.955 - 105)
    assert instant["margin_pct"] < patient["margin_pct"]


def test_station_margin_charges_broker_twice():
    r = trade.station_margin(100, 150, broker_fee=0.03, sales_tax=0.045)
    # cost 100*1.03=103, revenue 150*0.925=138.75, profit 35.75
    assert r["profit_isk"] == pytest.approx(35.75)
    assert r["margin_pct"] == pytest.approx(35.75 / 103, abs=1e-6)


def test_margin_negative_when_spread_too_thin():
    r = trade.patient_margin(100, 102, 0.03, 0.045, transport_cost=0)
    assert r["profit_isk"] < 0
    assert r["margin_pct"] < 0


def test_passes_filters_each_rejects_independently():
    kw = {"min_volume": 20, "max_cv": 0.15}
    assert trade.passes_filters(100, 0.1, 0.2, **kw) is True
    assert trade.passes_filters(5, 0.1, 0.2, **kw) is False      # liquidity
    assert trade.passes_filters(100, 0.5, 0.2, **kw) is False    # volatility
    assert trade.passes_filters(100, None, 0.2, **kw) is False   # no CV
    assert trade.passes_filters(100, 0.1, -0.01, **kw) is False  # spread


def test_plan_trade_caps_by_tightest_constraint():
    # budget 1000/price 100 = 10; cargo 50/vol 2 = 25; liquidity 1000 → min = 10
    p = trade.plan_trade(100, 2.0, profit_isk=20, daily_volume=1000, budget=1000, cargo=50)
    assert p["units"] == 10
    assert p["trip_profit"] == pytest.approx(200.0)
    assert p["trip_cost"] == pytest.approx(1000.0)


def test_plan_trade_cargo_binds():
    p = trade.plan_trade(100, 10.0, profit_isk=5, daily_volume=1e9, budget=1e9, cargo=50)
    assert p["units"] == 5    # 50 / 10


def test_plan_trade_liquidity_only_when_no_budget_or_cargo():
    p = trade.plan_trade(100, 2.0, profit_isk=5, daily_volume=7, budget=None, cargo=None)
    assert p["units"] == 7


def test_plan_trade_no_caps_returns_none():
    assert trade.plan_trade(100, 2.0, 5, None, None, None) == {
        "units": None, "trip_profit": None, "trip_cost": None}


def test_plan_trade_ignores_zero_buy_price_for_budget_cap():
    p = trade.plan_trade(0, 2.0, profit_isk=5, daily_volume=1e9, budget=1000, cargo=10)
    assert p["units"] == 5    # budget cap skipped (price 0), cargo 10/2 binds


def test_volume_scores_monotonic_and_edges():
    scores = trade.volume_scores({1: 0.0, 2: 100.0, 3: 10.0})
    assert scores[1] == pytest.approx(0.0) and scores[2] == pytest.approx(1.0)
    assert 0.0 < scores[3] < 1.0
    # degenerate sets
    assert trade.volume_scores({1: 50.0}) == {1: 1.0}
    assert trade.volume_scores({1: 0.0, 2: 0.0}) == {1: 0.0, 2: 0.0}
    assert trade.volume_scores({}) == {}
