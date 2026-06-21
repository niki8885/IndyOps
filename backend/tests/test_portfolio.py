"""Markowitz portfolio oracle: water-filling weights + integer allocation."""
import math

from app.services import portfolio


# ── optimize (weights) ────────────────────────────────────────────────────────

def test_weights_sum_to_one_and_nonnegative():
    w, m = portfolio.optimize([0.20, 0.10, 0.05], [0.30, 0.15, 0.05], 8.0)
    assert math.isclose(sum(w), 1.0, abs_tol=1e-9)
    assert all(x >= 0.0 for x in w)
    # low-volatility asset gets the most weight under risk aversion
    assert w[2] > w[1] > w[0]
    # closed-form check (hand-computed for these inputs)
    assert math.isclose(w[0], 0.220867, abs_tol=1e-4)
    assert math.isclose(w[2], 0.451220, abs_tol=1e-4)
    assert math.isclose(m["exp_return"], 0.099525, abs_tol=1e-4)
    assert m["stddev"] > 0.0


def test_single_asset_takes_everything():
    w, m = portfolio.optimize([0.12], [0.2], 8.0)
    assert w == [1.0]
    assert math.isclose(m["exp_return"], 0.12, abs_tol=1e-12)


def test_empty_universe():
    w, m = portfolio.optimize([], [], 8.0)
    assert w == []
    assert m["stddev"] == 0.0


def test_efficient_frontier_monotone_and_spans():
    mu, sig = [0.20, 0.10, 0.05], [0.30, 0.15, 0.05]
    fr = portfolio.efficient_frontier(mu, sig)
    assert len(fr) >= 2
    risks = [p["stddev"] for p in fr]
    assert risks == sorted(risks)                      # sorted by risk ascending
    assert fr[-1]["exp_return"] >= fr[0]["exp_return"]  # frontier slopes up
    assert abs(fr[-1]["exp_return"] - max(mu)) < 1e-6   # high-risk end → max-return asset
    assert portfolio.efficient_frontier([], []) == []


def test_higher_risk_aversion_diversifies_toward_low_vol():
    mu, sig = [0.20, 0.08], [0.40, 0.10]
    w_lo, _ = portfolio.optimize(mu, sig, 1.0)     # return-hungry
    w_hi, _ = portfolio.optimize(mu, sig, 50.0)    # risk-averse
    # the safe (low-σ) asset's share rises with risk aversion
    assert w_hi[1] > w_lo[1]


def test_zero_volatility_is_handled():
    # a near-riskless asset must not blow up (sigma floored), still sums to 1
    w, _ = portfolio.optimize([0.05, 0.05], [0.0, 0.20], 8.0)
    assert math.isclose(sum(w), 1.0, abs_tol=1e-9)
    assert w[0] > w[1]                              # prefers the riskless one


# ── build_portfolio (allocation) ──────────────────────────────────────────────

def _asset(tid, cost, profit, dv=10_000, vol=1.0):
    return {"type_id": tid, "name": f"T{tid}", "unit_cost": cost, "unit_profit": profit,
            "roi": profit / cost, "sigma": 0.1, "unit_vol_m3": vol, "daily_volume": dv,
            "best_method": "sell_buy"}


def test_allocation_fits_budget_and_caps_liquidity():
    assets = [_asset(1, 1_000.0, 100.0, dv=5), _asset(2, 2_000.0, 100.0, dv=10_000)]
    out = portfolio.build_portfolio(assets, [0.9, 0.1], budget=1_000_000.0, horizon_days=7)
    t = out["totals"]
    assert t["capital_used"] <= t["budget"] + 1e-6
    a1 = next(a for a in out["allocations"] if a["type_id"] == 1)
    assert a1["qty"] <= 5 * 7                       # liquidity cap = daily_volume·horizon
    assert t["expected_profit"] == round(sum(a["expected_profit"] for a in out["allocations"]), 2)


def test_leftover_reallocated_to_best_roi():
    # asset 2 has the higher ROI; after the weighted split, leftover should top it up
    assets = [_asset(1, 1_000.0, 50.0), _asset(2, 1_000.0, 300.0)]
    out = portfolio.build_portfolio(assets, [0.5, 0.5], budget=100_000.0, horizon_days=7)
    by_id = {a["type_id"]: a for a in out["allocations"]}
    assert by_id[2]["qty"] >= by_id[1]["qty"]
    assert out["totals"]["leftover"] >= 0.0
    assert out["totals"]["leftover"] < 1_000.0      # can't fit another unit


def test_unaffordable_asset_gets_zero():
    assets = [_asset(1, 5_000_000_000.0, 1.0)]
    out = portfolio.build_portfolio(assets, [1.0], budget=1_000_000.0, horizon_days=7)
    assert out["allocations"][0]["qty"] == 0
    assert out["totals"]["n_assets"] == 0
