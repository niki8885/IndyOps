"""The index-detail payload builder (pure, over a snapshot DataFrame)."""
import numpy as np
import pandas as pd

from app.services.index_report import compute_index_payload


def _df(n=60):
    rng = np.random.default_rng(0)
    ts = pd.date_range("2025-01-01", periods=n, freq="h")
    price = np.cumsum(rng.normal(0, 1, n)) + 100
    return pd.DataFrame({
        "timestamp": ts,
        "price": price,
        "volume": rng.integers(1, 100, n).astype(float),
        "top3_share": 0.5, "h_index": 0.3, "entropy": 1.2, "liquidity": 2.0,
    })


def test_payload_shape_and_keys():
    p = compute_index_payload(_df(), "mineral", "Minerals", "basket", 10)
    assert (p["key"], p["label"], p["kind"], p["window"]) == ("mineral", "Minerals", "basket", 10)
    assert {"timestamps", "series", "stats", "risk", "montecarlo", "heatmap", "states"} <= p.keys()
    assert len(p["timestamps"]) == 60
    assert len(p["series"]["price"]) == 60
    assert set(p["series"]) >= {"sma", "rsi", "macd", "tenkan", "volatility"}
    assert p["montecarlo"] is not None          # ≥10 points → GBM projection
    assert p["states"] is not None              # ≥6 volatility points → regimes
    assert len(p["heatmap"]) == 7 and all(len(r) == 24 for r in p["heatmap"])


def test_window_is_clamped():
    assert compute_index_payload(_df(20), "x", "X", "k", 1)["window"] == 2
