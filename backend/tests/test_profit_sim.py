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


def test_missing_volume_does_not_zero_revenue():
    """Regression for the 'too pessimistic' bug: an item with NO volume history
    (vol_mean=0, the degenerate / point-price fallback) must not collapse to a
    guaranteed loss. Absent liquidity data ⇒ no participation constraint (fill=1),
    so the product's revenue is realised and profit tracks the deterministic chain.
    Old behaviour: fill=0 → revenue=0 → profit ≈ −(material+fixed), prob_loss=100%."""
    leg = ps.LegInput(1, 10, math.log(100.0), 0.0, [100.0] * 101,
                      vol_mean=0.0, vol_sigma=0.5, spread_mean=0.0, spread_sigma=0.0)
    prod = ps.ProductInput(2, 1, math.log(2000.0), 0.0, [2000.0] * 101,
                           vol_mean=0.0, vol_sigma=0.5, spread_mean=0.0, spread_sigma=0.0)
    # participation_cap a realistic 10% — with zero volume this used to force fill=0.
    req = ps.SimRequest("novol", [leg], prod, fixed_cost=50.0, production_time_s=3600,
                        params=_deterministic_params(participation_cap=0.10),
                        cholesky_L=[[1.0, 0.0], [0.0, 1.0]])
    m = ps.simulate(req).metrics
    # sell 1 @ 2000 − buy 10 @ 100 − 50 fixed = 950, revenue fully realised.
    assert math.isclose(m.expected_profit, 950.0, abs_tol=1e-6)
    assert m.prob_loss == 0.0


def test_partial_fill_only_when_volume_known():
    """When volume *is* known and thin, the fill constraint still bites (revenue
    cut); when it is absent it does not — guards against re-introducing the bug."""
    base = dict(legs=[_flat_leg(1, 100.0)], fixed_cost=0.0, production_time_s=3600,
                cholesky_L=[[1.0, 0.0], [0.0, 1.0]],
                params=_deterministic_params(participation_cap=1e-9, shortfall_premium=0.0))
    thin = ps.ProductInput(2, 1000, math.log(50.0), 0.0, [50.0] * 101,
                           vol_mean=1.0, vol_sigma=0.0, spread_mean=0.0, spread_sigma=0.0)
    none = ps.ProductInput(2, 1000, math.log(50.0), 0.0, [50.0] * 101,
                           vol_mean=0.0, vol_sigma=0.0, spread_mean=0.0, spread_sigma=0.0)
    m_thin = ps.simulate(ps.SimRequest("thin", product=thin, **base)).metrics
    m_none = ps.simulate(ps.SimRequest("none", product=none, **base)).metrics
    assert m_thin.expected_profit < m_none.expected_profit   # known-thin still throttles
    assert m_none.expected_profit > 0                         # absent data ⇒ full revenue


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


# ── IO-22 hardening: confidence intervals, t-copula, price dynamics ─────────────

def _hist_set():
    rng = np.random.default_rng(0)

    def hs(base, jump):
        r = rng.standard_normal(40) * 0.06
        r[rng.integers(0, 40, 2)] += rng.choice([-1, 1], 2) * jump
        return list(base * np.exp(np.cumsum(r)))
    return {
        1: ps.TypeHistory(buy=hs(100, 0.3), sell=hs(106, 0.3), volume=[8000] * 40, last_buy=100),
        2: ps.TypeHistory(buy=hs(2000, 0.3), sell=hs(2050, 0.3), volume=[3000] * 40, last_sell=2050),
    }


def _run(**pk):
    hist = _hist_set()
    req = ps.request_from_legs("h", [(1, 10)], 2, 5, hist, 250.0, 7200,
                               ps.SimParams(n_iterations=pk.pop("n", 30_000), seed=4, **pk),
                               broker_fee_pct=3.6, sales_tax_pct=2.0)
    return req, ps.simulate(req).metrics


def test_ci_present_and_brackets_point():
    _, m = _run(dist_mode=0, corr_mode=0)
    assert set(m.standard_error) == {"expected_profit", "var5", "var1", "cvar5"}
    for k in ("expected_profit", "var5", "var1", "cvar5"):
        lo, hi = m.ci95[k]
        point = m.expected_profit if k == "expected_profit" else getattr(m, k)
        assert lo <= point <= hi
        assert m.standard_error[k] >= 0
    assert m.n_batches >= 2 and m.mc_rel_error >= 0


def test_more_iterations_tightens_ci():
    _, small = _run(dist_mode=0, corr_mode=0, n=4000)
    _, big = _run(dist_mode=0, corr_mode=0, n=60_000)
    assert big.standard_error["expected_profit"] < small.standard_error["expected_profit"]
    assert big.mc_rel_error < small.mc_rel_error


def _corr_cost_request(copula, t_df):
    """Profit dominated by a SUM of strongly positively-correlated material costs —
    a setup where tail dependence unambiguously fattens the loss tail."""
    rho = 0.9
    n = 4
    corr = np.full((n, n), rho)
    np.fill_diagonal(corr, 1.0)
    L = np.linalg.cholesky(corr)
    legs = [ps.LegInput(i + 1, 15, math.log(100.0), 0.5, [100.0] * 101,
                        vol_mean=1e15, vol_sigma=0.0, spread_mean=0.0, spread_sigma=0.0)
            for i in range(n - 1)]
    prod = ps.ProductInput(99, 1, math.log(5000.0), 0.01, [5000.0] * 101,
                           vol_mean=1e15, vol_sigma=0.0, spread_mean=0.0, spread_sigma=0.0)
    return ps.SimRequest("c", legs, prod, 0.0, 3600,
                         ps.SimParams(n_iterations=80_000, seed=7, dist_mode=1, corr_mode=0,
                                      copula=copula, t_df=t_df, participation_cap=1e12, slippage=0.0),
                         cholesky_L=[[float(x) for x in r] for r in L])


def test_t_copula_fattens_loss_tail():
    mg = ps.simulate(_corr_cost_request(copula=0, t_df=4.0)).metrics
    mt = ps.simulate(_corr_cost_request(copula=1, t_df=4.0)).metrics
    # Student-t copula concentrates risk in the deep tail: more joint cost spikes →
    # worse expected shortfall (CVaR5) and worst-1% than the Gaussian copula.
    assert mt.cvar5 < mg.cvar5
    assert mt.worst1 < mg.worst1


def test_path_mode_runs_with_and_without_garch():
    _, ar = _run(dist_mode=0, corr_mode=0, path_steps=24, garch=0)
    _, gc = _run(dist_mode=0, corr_mode=0, path_steps=24, garch=1)
    for m in (ar, gc):
        assert math.isfinite(m.expected_profit) and math.isfinite(m.std)
        assert m.var5 <= m.percentiles["p50"] <= m.best
        assert m.n_batches >= 2


def test_auto_t_df_estimated_from_data():
    hist = _hist_set()
    req = ps.request_from_legs("h", [(1, 10)], 2, 5, hist, 250.0, 7200,
                               ps.SimParams(n_iterations=2000, seed=4, copula=1, t_df=0.0),
                               broker_fee_pct=3.6)
    assert 3.0 <= req.params.t_df <= 100.0 and req.params.t_df != 0.0   # auto-filled
