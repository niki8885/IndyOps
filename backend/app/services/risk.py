"""
Risk / market-state analytics over a returns or volatility series.

Extracted from analysis_router (index_detail): historical VaR/CVaR, return
distribution histogram, Monte-Carlo (GBM) price-path projection, weekday×hour
volume heatmap and volatility-regime terciles. numpy/pandas only — no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from ._numeric import clean


@dataclass
class VarResult:
    var95: Optional[float]
    cvar95: Optional[float]
    hist_counts: Optional[list]
    hist_edges: Optional[list]


@dataclass
class MonteCarlo:
    horizon: int
    p5: list
    p50: list
    p95: list
    final_p5: Optional[float]
    final_p50: Optional[float]
    final_p95: Optional[float]


@dataclass
class MarketStates:
    labels: list           # 0 calm / 1 normal / 2 turbulent, per point
    names: list
    current: Optional[int]
    thresholds: list
    counts: list


def histogram(values: pd.Series, min_bins: int = 10) -> tuple[Optional[list], Optional[list]]:
    """(counts, edges) for a value series, or (None, None) if < 5 points."""
    v = pd.Series(values).dropna()
    if len(v) < 5:
        return None, None
    counts, edges = np.histogram(v, bins=min(30, max(min_bins, len(v) // 3)))
    return counts.tolist(), [float(e) for e in edges]


def value_at_risk(returns: pd.Series) -> VarResult:
    """Historical 95% VaR/CVaR + return-distribution histogram."""
    rclean = returns.dropna()
    var95 = cvar95 = None
    if len(rclean) >= 5:
        var95 = float(np.percentile(rclean, 5))
        tail = rclean[rclean <= var95]
        cvar95 = float(tail.mean()) if len(tail) else var95
    hist_counts, hist_edges = histogram(rclean, min_bins=10)
    return VarResult(var95, cvar95, hist_counts, hist_edges)


def monte_carlo_gbm(returns: pd.Series, last_price: float,
                    horizon: int = 24, n_paths: int = 500, seed: int = 42) -> Optional[MonteCarlo]:
    """Geometric-Brownian-Motion projection of ``last_price`` over ``horizon`` steps."""
    rclean = returns.dropna()
    if len(rclean) < 10:
        return None
    logret = np.log1p(rclean.values)
    mu, sigma = float(np.mean(logret)), float(np.std(logret))
    rng = np.random.default_rng(seed)
    shocks = rng.normal(mu, sigma, size=(n_paths, horizon))
    paths = last_price * np.exp(np.cumsum(shocks, axis=1))
    return MonteCarlo(
        horizon=horizon,
        p5=[float(x) for x in np.percentile(paths, 5, axis=0)],
        p50=[float(x) for x in np.percentile(paths, 50, axis=0)],
        p95=[float(x) for x in np.percentile(paths, 95, axis=0)],
        final_p5=clean(np.percentile(paths[:, -1], 5)),
        final_p50=clean(np.percentile(paths[:, -1], 50)),
        final_p95=clean(np.percentile(paths[:, -1], 95)),
    )


def volume_heatmap(df: pd.DataFrame) -> list:
    """7×24 grid (weekday × hour) of mean volume. ``df`` needs timestamp + volume."""
    dfh = df.copy()
    dfh["wd"] = dfh["timestamp"].dt.weekday
    dfh["hr"] = dfh["timestamp"].dt.hour
    heat = [[None] * 24 for _ in range(7)]
    if dfh["volume"].notna().any():
        grp = dfh.groupby(["wd", "hr"])["volume"].mean()
        for (wd, hr), v in grp.items():
            heat[int(wd)][int(hr)] = clean(v)
    return heat


def volatility_regimes(volatility: pd.Series) -> Optional[MarketStates]:
    """Tercile volatility regimes (calm/normal/turbulent). None if < 6 points."""
    vclean = volatility.dropna()
    if len(vclean) < 6:
        return None
    q1, q2 = np.percentile(vclean, [33, 66])

    def regime(v):
        if pd.isna(v):
            return None
        return 0 if v <= q1 else (1 if v <= q2 else 2)

    labels = [regime(v) for v in volatility]
    cur = next((labels[i] for i in range(len(labels) - 1, -1, -1) if labels[i] is not None), None)
    return MarketStates(
        labels=labels,
        names=["Calm", "Normal", "Turbulent"],
        current=cur,
        thresholds=[clean(q1), clean(q2)],
        counts=[int(sum(1 for l in labels if l == k)) for k in range(3)],
    )
