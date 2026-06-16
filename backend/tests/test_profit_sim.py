"""Monte-Carlo profit simulator — the pure Python oracle."""
import math

import numpy as np
import pytest

from app.services import profit_sim as ps


def _flat_leg(qty, price, **kw):
    return ps.LegInput(1, qty, math.log(price), 0.0, [price] * 101,
                       vol_mean=1e15, vol_sigma=0.0, spread_mean=0.0, spread_sigma=0.0, **kw)


def _flat_product(qty, price, **kw):
    return ps.ProductInput(2, qty, math.log(price), 0.0, [price] * 101,
                           vol_mean=1e15, vol_sigma=0.0, spread_mean=0.0, spread_sigma=0.0, **kw)


def _deterministic_params(**kw):
    base = dict(n_iterations=5000, seed=1, dist_mode=1, slippage=0.0,
                participation_cap=1e12, shortfall_premium=0.0, haul_delay_prob=0.0)
    base.update(kw)
    return ps.SimParams(**base)


def test_deterministic_profit_matches_closed_form():
    # sell 1 @ 2000 (3.6% broker) − buy 10 @ 100 − 50 fixed = 1928 − 1000 − 50 = 878
    req = ps.SimRequest("t", [_flat_leg(10, 100.0)], _flat_product(1, 2000.0, broker_fee_pct=3.6),
                        fixed_cost=50.0, production_time_s=3600, params=_deterministic_params(),
                        cholesky_L=[[1.0, 0.0], [0.0, 1.0]])
    m = ps.simulate(req).metrics
    assert math.isclose(m.expected_profit, 878.0, abs_tol=1e-6)
    assert m.std < 1e-6 and m.prob_loss == 0.0
    assert m.var5 == pytest.approx(878.0, abs=1e-6)


def test_metrics_formulas_on_known_profit():
    # drive _metrics directly with a known profit vector
    profit = np.array([-100.0, -50, 0, 50, 100, 150, 200, 250, 300, 350])
    req = ps.SimRequest("t", [_flat_leg(1, 1.0)], _flat_product(1, 1.0),
                        0.0, 7200, _deterministic_params(slots=2, risk_lambda=1.0))
    m = ps._metrics(req, profit, np.full(profit.size, 2.0), {
        "material_cost": np.zeros(10), "revenue": profit, "taxes_fees": np.zeros(10),
        "logistics": np.zeros(10)})
    assert math.isclose(m.expected_profit, profit.mean())
    assert math.isclose(m.std, profit.std(ddof=0))
    assert math.isclose(m.prob_loss, 0.2)                  # 2 of 10 negative
    assert math.isclose(m.sharpe_like, profit.mean() / profit.std(ddof=0))
    assert math.isclose(m.risk_adjusted, profit.mean() - profit.std(ddof=0))
    assert math.isclose(m.return_per_slot, profit.mean() / 2)
    assert math.isclose(m.time_per_job_h, 7200 / 3600 / 2)  # slots=2


def test_shortfall_premium_raises_material_cost():
    # finite material liquidity → at a tiny participation cap it can't fill →
    # the shortfall premium kicks in and lowers profit
    leg = ps.LegInput(1, 1000, math.log(100.0), 0.0, [100.0] * 101,
                      vol_mean=1e6, vol_sigma=0.0, spread_mean=0.0, spread_sigma=0.0)
    base = dict(label="t", legs=[leg], product=_flat_product(1, 2_000_000.0),
                fixed_cost=0.0, production_time_s=3600, cholesky_L=[[1.0, 0.0], [0.0, 1.0]])
    full = ps.simulate(ps.SimRequest(params=_deterministic_params(participation_cap=1e12), **base)).metrics
    starved = ps.simulate(ps.SimRequest(
        params=_deterministic_params(participation_cap=1e-9, shortfall_premium=0.5), **base)).metrics
    assert starved.expected_profit < full.expected_profit


def test_correlation_propagates_to_sampled_prices():
    # strongly correlated buy & sell (lognormal) → sampled prices co-move
    L = ps.market_model.nearest_psd_cholesky(np.array([[1.0, 0.9], [0.9, 1.0]]))
    leg = ps.LegInput(1, 1, math.log(100.0), 0.3, [100.0] * 101, 1e15, 0.0, 0.0, 0.0)
    prod = ps.ProductInput(2, 1, math.log(100.0), 0.3, [100.0] * 101, 1e15, 0.0, 0.0, 0.0)
    req = ps.SimRequest("t", [leg], prod, 0.0, 3600,
                        ps.SimParams(n_iterations=80_000, seed=3, dist_mode=1),
                        cholesky_L=[[float(x) for x in r] for r in L])
    rng = np.random.default_rng(req.params.seed)
    z = rng.standard_normal((req.params.n_iterations, 2)) @ np.asarray(L).T
    assert abs(np.corrcoef(z, rowvar=False)[0, 1] - 0.9) < 0.01


def test_factor_mode_runs_and_is_finite():
    hist = {
        1: ps.TypeHistory(buy=[95, 100, 105, 98, 110], sell=[100, 106, 110, 103, 116],
                          volume=[1e6] * 5, group_id=0, last_buy=100),
        2: ps.TypeHistory(buy=[1900, 2000, 2100], sell=[1950, 2050, 2150, 2000, 2100],
                          volume=[5000] * 5, group_id=1, last_sell=2050),
    }
    req = ps.request_from_legs("x", [(1, 10)], 2, 1, hist, 50.0, 3600,
                               ps.SimParams(n_iterations=20_000, seed=7, dist_mode=0, corr_mode=1),
                               broker_fee_pct=3.6)
    assert req.loadings is not None and req.idio_sigma is not None
    m = ps.simulate(req).metrics
    assert math.isfinite(m.expected_profit) and math.isfinite(m.std)
    assert m.var5 <= m.percentiles["p50"] <= m.best


def test_empirical_run_has_dispersion_and_histograms():
    hist = {
        1: ps.TypeHistory(buy=[95, 100, 105, 98, 102, 110, 90],
                          sell=[100, 106, 110, 103, 108, 116, 95], volume=[1e6] * 7, last_buy=100),
        2: ps.TypeHistory(buy=[1900, 2000, 2100], sell=[1950, 2050, 2150, 2000, 2100],
                          volume=[5000] * 5, last_sell=2050),
    }
    m = ps.simulate(ps.request_from_legs(
        "x", [(1, 10)], 2, 1, hist, 50.0, 3600,
        ps.SimParams(n_iterations=30_000, seed=7, dist_mode=0), broker_fee_pct=3.6)).metrics
    assert m.std > 0                                  # real uncertainty
    assert len(m.hist_counts) == 40 and len(m.hist_edges) == 41
    assert sum(m.hist_counts) == m.n_iterations
    assert set(m.breakdown) == {"material_cost", "revenue", "taxes_fees", "logistics"}


def test_rank_strategies_orders_by_composite_score():
    items = [
        ps.RankInput("A", expected_profit=1000, sharpe_like=2.0, var5=-50,
                     return_per_slot=1000, return_per_time=10, prob_loss=0.1),
        ps.RankInput("B", expected_profit=500, sharpe_like=0.5, var5=-300,
                     return_per_slot=500, return_per_time=5, prob_loss=0.4),
        ps.RankInput("C", expected_profit=1200, sharpe_like=1.0, var5=-200,
                     return_per_slot=600, return_per_time=8, prob_loss=0.2),
    ]
    ranked = ps.rank_strategies(items)
    assert [r.label for r in ranked] == ["A", "C", "B"]
    assert [r.rank for r in ranked] == [1, 2, 3]


def test_rank_single_strategy():
    ranked = ps.rank_strategies([ps.RankInput("solo", 1, 1, 1, 1, 1, 0.1)])
    assert ranked == [ps.RankedStrategy(rank=1, label="solo", score=0.0)]
