"""Risk analytics: VaR/CVaR, Monte-Carlo determinism, volatility regimes."""
import numpy as np
import pandas as pd

from app.services.risk import monte_carlo_gbm, value_at_risk, volatility_regimes, volume_heatmap


def test_var_none_when_too_few_points():
    r = value_at_risk(pd.Series([0.01, 0.02]))
    assert r.var95 is None and r.cvar95 is None
    assert r.hist_counts is None


def test_var_cvar_ordering():
    rng = np.random.default_rng(0)
    returns = pd.Series(rng.normal(0, 0.02, 500))
    r = value_at_risk(returns)
    # CVaR is the mean of the worst tail, so it sits at or below the 5% VaR.
    assert r.cvar95 <= r.var95
    assert r.hist_counts is not None and len(r.hist_edges) == len(r.hist_counts) + 1


def test_monte_carlo_is_seed_deterministic():
    returns = pd.Series(np.linspace(-0.01, 0.01, 50))
    a = monte_carlo_gbm(returns, 100.0, seed=7)
    b = monte_carlo_gbm(returns, 100.0, seed=7)
    assert a.p50 == b.p50 and a.final_p95 == b.final_p95
    assert len(a.p50) == a.horizon == 24


def test_monte_carlo_none_when_too_few():
    assert monte_carlo_gbm(pd.Series([0.0, 0.01]), 100.0) is None


def test_volume_heatmap_weekday_hour_means():
    # Mon 10:00 + Mon 10:30 average together; Tue 15:00 stands alone.
    ts = pd.to_datetime(["2025-01-06 10:00", "2025-01-06 10:30", "2025-01-07 15:00"])
    df = pd.DataFrame({"timestamp": ts, "volume": [10.0, 20.0, 5.0]})
    heat = volume_heatmap(df)
    assert len(heat) == 7 and all(len(row) == 24 for row in heat)
    assert heat[0][10] == 15.0     # Monday (wd 0), hour 10
    assert heat[1][15] == 5.0      # Tuesday (wd 1), hour 15
    assert heat[3][8] is None      # untouched cell stays None


def test_volatility_regimes():
    vol = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
    s = volatility_regimes(vol)
    assert s is not None
    assert s.names == ["Calm", "Normal", "Turbulent"]
    assert s.current in (0, 1, 2)
    assert sum(s.counts) == len(vol)


def test_volatility_regimes_none_when_too_few():
    assert volatility_regimes(pd.Series([0.1, 0.2, 0.3, 0.4, 0.5])) is None


def test_volatility_regimes_skip_nan_points():
    vol = pd.Series([0.1, np.nan, 0.3, 0.4, 0.5, 0.6, 0.7, np.nan])
    s = volatility_regimes(vol)
    assert s is not None
    assert None in s.labels          # NaN points are left unlabelled
    assert sum(s.counts) == 6        # only the 6 real points are bucketed
