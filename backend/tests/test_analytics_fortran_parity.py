"""
Parity: the Fortran port (fortran/analytics-engine) must agree with the Python
core (index_report.compute_index_payload, the oracle) on the same snapshot.

Deterministic metrics (indicators, VaR/CVaR, histogram, regimes, heatmap, stats)
match within a tight float tolerance — floating-point replication, not bit-exact
by contract. Monte-Carlo bands match *statistically*: the engine uses its own
seed-deterministic RNG (xoshiro256**/Box-Muller), not numpy's PCG64/Ziggurat, so
reproducing exact draws is neither possible nor a meaningful notion of accuracy —
see fortran/analytics-engine/rng.f90. With identical mu/sigma the bands converge
to the same log-normal quantiles, which is what we assert.

Skipped automatically where the binary isn't built (ANALYTICS_ENGINE_BIN or the
default fortran/analytics-engine/bin/analytics-engine[.exe]).
"""
import math

import numpy as np
import pandas as pd
import pytest

from app.adapters import analytics_engine
from app.services.index_report import compute_index_payload

pytestmark = pytest.mark.skipif(not analytics_engine.available(),
                                reason="analytics-engine binary not built on this host")

RTOL, ATOL = 1e-7, 1e-9   # deterministic fields: ~ULP-level agreement in practice
MC_TOL = 0.10             # Monte-Carlo bands: statistical convergence (observed << 2%)


def _df(n, kind, seed=0):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2025-01-01", periods=n, freq="h")
    if kind == "walk":
        price = np.cumsum(rng.normal(0, 1, n)) + 100
    elif kind == "trend":
        price = 100 + 0.5 * np.arange(n) + rng.normal(0, 0.7, n)
    else:  # "vol" — oscillating, exercises tercile regimes
        price = 100 + 8 * np.sin(np.arange(n) / 5.0) + rng.normal(0, 1.5, n)
    vol = rng.integers(1, 100, n).astype(float)
    vol[rng.integers(0, n, max(1, n // 20))] = np.nan   # some missing volume
    return pd.DataFrame({
        "timestamp": ts, "price": price, "volume": vol,
        "top3_share": 0.5, "h_index": 0.3, "entropy": 1.2, "liquidity": 2.0,
    })


FIXTURES = {
    "walk60": lambda: _df(60, "walk"),
    "walk30": lambda: _df(30, "walk", seed=3),
    "trend200": lambda: _df(200, "trend"),
    "vol120": lambda: _df(120, "vol"),
    "small12": lambda: _df(12, "walk", seed=7),   # MC present, regimes None
    "tiny8": lambda: _df(8, "walk", seed=1),       # VaR present, MC None
    "tiny4": lambda: _df(4, "walk", seed=2),       # VaR/MC/regimes all None
}


def _is_null(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def _close(a, b):
    if _is_null(a) or _is_null(b):
        return _is_null(a) and _is_null(b)
    return math.isclose(a, b, rel_tol=RTOL, abs_tol=ATOL)


def _assert_array(name, a, b):
    assert (a is None) == (b is None), f"{name}: None mismatch"
    if a is None:
        return
    assert len(a) == len(b), f"{name}: length {len(a)} vs {len(b)}"
    for i, (x, y) in enumerate(zip(a, b)):
        assert _close(x, y), f"{name}[{i}]: {x} vs {y}"


@pytest.mark.parametrize("name", list(FIXTURES))
def test_fortran_matches_python(name):
    df = FIXTURES[name]()
    py = compute_index_payload(df, name, name.upper(), "basket", 10)
    fo = analytics_engine.compute_native(df, name, name.upper(), "basket", 10)

    # echoed pass-through fields
    assert (py["key"], py["label"], py["kind"], py["window"]) == \
           (fo["key"], fo["label"], fo["kind"], fo["window"])
    assert py["timestamps"] == fo["timestamps"]

    # deterministic indicator series
    assert set(py["series"]) == set(fo["series"])
    for k in py["series"]:
        _assert_array(f"series.{k}", py["series"][k], fo["series"][k])

    # headline stats
    assert set(py["stats"]) == set(fo["stats"])
    for k in py["stats"]:
        if k == "points":
            assert py["stats"][k] == fo["stats"][k]
        else:
            assert _close(py["stats"][k], fo["stats"][k]), \
                f"stats.{k}: {py['stats'][k]} vs {fo['stats'][k]}"

    # risk: VaR/CVaR within tolerance, histogram counts exact
    assert _close(py["risk"]["var95"], fo["risk"]["var95"])
    assert _close(py["risk"]["cvar95"], fo["risk"]["cvar95"])
    assert py["risk"]["hist_counts"] == fo["risk"]["hist_counts"]
    _assert_array("risk.hist_edges", py["risk"]["hist_edges"], fo["risk"]["hist_edges"])

    # volume heatmap (7×24)
    assert len(py["heatmap"]) == len(fo["heatmap"]) == 7
    for r, (ra, rb) in enumerate(zip(py["heatmap"], fo["heatmap"])):
        _assert_array(f"heatmap[{r}]", ra, rb)

    # volatility regimes
    assert (py["states"] is None) == (fo["states"] is None)
    if py["states"] is not None:
        assert py["states"]["labels"] == fo["states"]["labels"]
        assert py["states"]["names"] == fo["states"]["names"]
        assert py["states"]["current"] == fo["states"]["current"]
        assert py["states"]["counts"] == fo["states"]["counts"]
        _assert_array("states.thresholds", py["states"]["thresholds"], fo["states"]["thresholds"])

    # Monte-Carlo — statistical parity
    assert (py["montecarlo"] is None) == (fo["montecarlo"] is None)
    if py["montecarlo"] is not None:
        a, b = py["montecarlo"], fo["montecarlo"]
        assert a["horizon"] == b["horizon"]
        assert len(b["p5"]) == len(b["p50"]) == len(b["p95"]) == b["horizon"]
        for i in range(b["horizon"]):                       # native bands ordered
            assert b["p5"][i] <= b["p50"][i] <= b["p95"][i] + 1e-9
        for band in ("p5", "p50", "p95"):                   # converge to the oracle
            for x, y in zip(a[band], b[band]):
                assert abs(x / y - 1.0) < MC_TOL, f"mc.{band}: {x} vs {y}"
        for k in ("final_p5", "final_p50", "final_p95"):
            assert abs(a[k] / b[k] - 1.0) < MC_TOL, f"mc.{k}: {a[k]} vs {b[k]}"
