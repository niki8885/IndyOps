"""
Parity: the Fortran demand core (fortran/analytics-engine → demand-engine) must
agree with the Python oracle (services.demand.demand_payload) on the same history.

Every demand metric is deterministic (no Monte-Carlo), so all fields match within
a tight float tolerance — floating-point replication, not bit-exact by contract.

Skipped automatically where the binary isn't built (DEMAND_ENGINE_BIN or the
default fortran/analytics-engine/bin/demand-engine[.exe]).
"""
import math

import numpy as np
import pandas as pd
import pytest

from app.adapters import demand_engine
from app.services.demand import demand_payload

pytestmark = pytest.mark.skipif(not demand_engine.available(),
                                reason="demand-engine binary not built on this host")

RTOL, ATOL = 1e-7, 1e-9


def _history(n, seed=0, intermittent=False):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2025-01-01", periods=n, freq="D")
    price = np.cumsum(rng.normal(0, 1.5, n)) + 100
    vol = (1000 + 8 * np.arange(n) + 300 * np.sin(np.arange(n) / 7.0)
           + rng.normal(0, 120, n)).clip(min=0)
    if intermittent:
        vol[rng.integers(0, n, max(1, n // 4))] = 0          # dead trading days
    vol[rng.integers(0, n, max(1, n // 25))] = np.nan        # missing candles
    oc = rng.integers(5, 60, n).astype(float)
    rows = []
    for i in range(n):
        rows.append({
            "date": ts[i].strftime("%Y-%m-%d"),
            "average": float(price[i]),
            "highest": float(price[i]) * 1.03,
            "lowest": float(price[i]) * 0.97,
            "volume": None if np.isnan(vol[i]) else float(vol[i]),
            "order_count": float(oc[i]),
        })
    return rows


BOOK = {"bid_depth": 5000, "ask_depth": 8000, "best_bid": 150.0, "best_ask": 152.0,
        "spread": 2.0, "spread_pct": 1.3245, "mid": 151.0}
BOOK_NO_BID = {"bid_depth": 0, "ask_depth": 0, "best_bid": None, "best_ask": None,
               "spread": None, "spread_pct": None, "mid": None}

FIXTURES = {
    "big200": (lambda: _history(200, 1), BOOK),
    "mid120": (lambda: _history(120, 2), BOOK),
    "intermittent90": (lambda: _history(90, 3, intermittent=True), BOOK),
    "short45": (lambda: _history(45, 4), BOOK),            # n<60 → prev30/trend_pct None
    "tiny12": (lambda: _history(12, 5), BOOK_NO_BID),      # n<14 autocorr None, empty book
    "tiny4": (lambda: _history(4, 6), None),               # n<5 slope/trend_line None, book None
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
    make, book = FIXTURES[name]
    hist = make()
    py = demand_payload(hist, 34, name, "The Forge", book)
    fo = demand_engine.compute_native(hist, 34, name, "The Forge", book)

    # echoed pass-through fields
    assert (py["type_id"], py["label"], py["region_name"]) == \
           (fo["type_id"], fo["label"], fo["region_name"])
    assert py["timestamps"] == fo["timestamps"]

    assert set(py["series"]) == set(fo["series"])
    for k in py["series"]:
        _assert_array(f"series.{k}", py["series"][k], fo["series"][k])

    assert set(py["stats"]) == set(fo["stats"])
    for k in py["stats"]:
        if k == "points":
            assert py["stats"][k] == fo["stats"][k]
        else:
            assert _close(py["stats"][k], fo["stats"][k]), \
                f"stats.{k}: {py['stats'][k]} vs {fo['stats'][k]}"

    assert set(py["book"]) == set(fo["book"])
    for k in py["book"]:
        assert _close(py["book"][k], fo["book"][k]), \
            f"book.{k}: {py['book'][k]} vs {fo['book'][k]}"

    _assert_array("weekday_volume", py["weekday_volume"], fo["weekday_volume"])
    assert _close(py["weekend_lift"], fo["weekend_lift"]), "weekend_lift"
    assert _close(py["weekly_autocorr"], fo["weekly_autocorr"]), "weekly_autocorr"

    assert set(py["score"]) == set(fo["score"])
    for k in py["score"]:
        assert _close(py["score"][k], fo["score"][k]), \
            f"score.{k}: {py['score'][k]} vs {fo['score'][k]}"
