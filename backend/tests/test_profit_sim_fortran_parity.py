"""
Parity: the Fortran profit-sim (fortran/analytics-engine → profit-sim) must agree
with the Python oracle (services.profit_sim.simulate) on the same request.

Parity is **statistical**, not bit-exact: the engine uses its own seed-deterministic
RNG (xoshiro256**/Box–Muller), not numpy's PCG64, so reproducing a particular draw
stream is impossible and not a meaningful measure of accuracy — see
fortran/analytics-engine/src/rng.f90. With the same model and enough paths the
metrics converge: monetary metrics match within a small relative tolerance,
probabilities within an absolute one (they live in [0,1] where rel-tol explodes).

Skipped automatically where the binary isn't built (PROFIT_SIM_BIN or the default
fortran/analytics-engine/bin/profit-sim[.exe]).
"""
import math

import pytest

from app.adapters import profit_sim as eng
from app.services import profit_sim as ps

pytestmark = pytest.mark.skipif(not eng.available(),
                                reason="profit-sim binary not built on this host")

REL = 0.05    # monetary metrics: statistical convergence at 50k paths (observed << 1%)
ABS_P = 0.03  # probabilities (prob_loss): absolute tolerance


def _hist(group_id=0, **kw):
    return ps.TypeHistory(group_id=group_id, **kw)


_HIST = {
    1: _hist(buy=[95, 100, 105, 98, 102, 110, 90, 99, 101, 108],
             sell=[100, 106, 110, 103, 108, 116, 95, 104, 107, 114], volume=[8000] * 10, last_buy=100),
    3: _hist(buy=[40, 42, 38, 41, 43, 39, 44], sell=[42, 44, 40, 43, 45, 41, 46],
             volume=[20000] * 7, last_buy=42),
    2: _hist(group_id=1, buy=[1900, 2000, 2100, 1950, 2050],
             sell=[1950, 2050, 2150, 2000, 2100], volume=[3000] * 5, last_sell=2050),
}


def _req(**pk):
    params = ps.SimParams(**{"n_iterations": 50_000, "participation_cap": 0.3, **pk})
    return ps.request_from_legs("parity", [(1, 10), (3, 50)], 2, 5, _HIST,
                                fixed_cost=250.0, production_time_s=7200, params=params,
                                broker_fee_pct=3.6, sales_tax_pct=2.0)


FIXTURES = {
    "empirical_cholesky": lambda: _req(seed=1, dist_mode=0, corr_mode=0),
    "empirical_factor": lambda: _req(seed=2, dist_mode=0, corr_mode=1),
    "lognormal_cholesky": lambda: _req(seed=3, dist_mode=1, corr_mode=0),
    "lognormal_factor": lambda: _req(seed=4, dist_mode=1, corr_mode=1),
    "low_liquidity_premium": lambda: _req(seed=5, dist_mode=0, corr_mode=0,
                                          participation_cap=0.02, shortfall_premium=0.5),
    "with_logistics": lambda: _req(seed=6, dist_mode=0, corr_mode=0,
                                   haul_delay_prob=0.3, haul_delay_hours_mean=48.0,
                                   holding_daily_rate=0.01),
}

_MONETARY = ["expected_profit", "median_profit", "std", "var5", "var1", "cvar5", "worst1"]


@pytest.mark.parametrize("name", list(FIXTURES))
def test_fortran_matches_python(name):
    req = FIXTURES[name]()
    native = eng.compute_native(req)
    oracle = ps.simulate(req)
    a, b = native.metrics, oracle.metrics

    assert native.engine == "fortran"
    assert a.n_iterations == b.n_iterations == req.params.n_iterations

    for k in _MONETARY:
        x, y = getattr(a, k), getattr(b, k)
        assert abs(x - y) <= REL * (abs(y) + 1.0), f"{k}: {x} vs {y}"

    assert abs(a.prob_loss - b.prob_loss) <= ABS_P

    # ordered percentiles, present on both
    assert set(a.percentiles) == set(b.percentiles)
    for q in a.percentiles:
        assert abs(a.percentiles[q] - b.percentiles[q]) <= REL * (abs(b.percentiles[q]) + 1.0)
    assert a.worst <= a.percentiles["p50"] <= a.best

    # histograms: same shape, full count
    assert len(a.hist_counts) == len(b.hist_counts) == 40
    assert sum(a.hist_counts) == req.params.n_iterations

    # breakdown components present and means converge
    assert set(a.breakdown) == {"material_cost", "revenue", "taxes_fees", "logistics"}
    for comp, stats in a.breakdown.items():
        assert abs(stats["mean"] - b.breakdown[comp]["mean"]) <= REL * (abs(b.breakdown[comp]["mean"]) + 1.0)

    # time metrics
    assert math.isclose(a.time_per_job_h, b.time_per_job_h, rel_tol=1e-9)
    assert abs(a.time_mean_h - b.time_mean_h) <= 0.10 * (abs(b.time_mean_h) + 1.0)

    # ranking-relevant scalars
    for k in ("sharpe_like", "risk_adjusted", "return_per_slot", "return_per_time", "cv"):
        x, y = getattr(a, k), getattr(b, k)
        assert abs(x - y) <= 0.10 * (abs(y) + 1.0), f"{k}: {x} vs {y}"
