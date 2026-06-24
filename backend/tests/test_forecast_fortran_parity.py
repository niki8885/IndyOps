"""
Parity: the native forecast-engine (fortran/analytics-engine → forecast-engine)
must agree with the Python oracle (services.forecast) on the same history.

The whole panel is deterministic (model fits, walk-forward backtest, P10/P50/P90
bands; SARIMA via CSS+Nelder-Mead from identical init) so the selected model,
forecast bands, metrics, signal and turnover all match within a tight float
tolerance. Skipped where the binary isn't built (FORECAST_ENGINE_BIN / default).
"""
import math

import numpy as np
import pandas as pd
import pytest

from app.adapters import forecast_engine
from app.services import forecast as forecast_oracle

pytestmark = pytest.mark.skipif(not forecast_engine.available(),
                                reason="forecast-engine binary not built on this host")

RTOL, ATOL = 1e-6, 1e-6


def _history(n, seed, kind):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2025-01-01", periods=n, freq="D")
    if kind == "seasonal":
        vol = (1000 + 6 * np.arange(n) + 350 * np.sin(np.arange(n) / 7 * 2 * np.pi)
               + rng.normal(0, 80, n)).clip(0)
    elif kind == "intermittent":
        vol = (rng.poisson(0.4, n) * rng.integers(40, 200, n)).astype(float)
    else:
        vol = (2000 + rng.normal(0, 150, n)).clip(0)
    price = np.cumsum(rng.normal(0, 0.8, n)) + 100
    return [{"date": ts[i].strftime("%Y-%m-%d"), "average": float(price[i]),
             "highest": float(price[i]) * 1.02, "lowest": float(price[i]) * 0.98,
             "volume": float(vol[i]), "order_count": float(rng.integers(5, 40))}
            for i in range(n)]


FIXTURES = {
    "seasonal_160_30": ("seasonal", 160, 30),
    "seasonal_120_7": ("seasonal", 120, 7),
    "intermittent_160_30": ("intermittent", 160, 30),
    "intermittent_90_30": ("intermittent", 90, 30),
    "flat_160_30": ("flat", 160, 30),
    "flat_120_7": ("flat", 120, 7),
}


def _is_null(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def _close(a, b):
    if _is_null(a) or _is_null(b):
        return _is_null(a) and _is_null(b)
    return math.isclose(a, b, rel_tol=RTOL, abs_tol=ATOL)


def _assert_arr(name, a, b):
    assert len(a) == len(b), f"{name}: length {len(a)} vs {len(b)}"
    for i, (x, y) in enumerate(zip(a, b)):
        assert _close(x, y), f"{name}[{i}]: {x} vs {y}"


@pytest.mark.parametrize("name", list(FIXTURES))
def test_forecast_fortran_matches_python(name):
    kind, n, h = FIXTURES[name]
    hist = _history(n, hash(name) % 1000, kind)
    py = forecast_oracle.forecast_payload(hist, 34, name, "The Forge", h)
    fo = forecast_engine.compute_native(hist, 34, name, "The Forge", h)

    assert py["future"] == fo["future"]
    for tgt in ("volume", "price"):
        a, b = py[tgt], fo[tgt]
        assert a["model"] == b["model"], f"{tgt} model: {a['model']} vs {b['model']}"
        for band in ("p50", "p10", "p90"):
            _assert_arr(f"{tgt}.{band}", a[band], b[band])
        for k in a["backtest"]:
            assert _close(a["backtest"][k], b["backtest"][k]), \
                f"{tgt}.backtest.{k}: {a['backtest'][k]} vs {b['backtest'][k]}"
        assert [c["model"] for c in a["candidates"]] == [c["model"] for c in b["candidates"]]
        for ca, cb in zip(a["candidates"], b["candidates"]):
            assert _close(ca["mase"], cb["mase"]), f"{tgt} cand {ca['model']} mase"

    _assert_arr("isk_turnover.p50", py["isk_turnover"]["p50"], fo["isk_turnover"]["p50"])
    assert py["signal"]["action"] == fo["signal"]["action"]
    assert _close(py["signal"]["score"], fo["signal"]["score"])
