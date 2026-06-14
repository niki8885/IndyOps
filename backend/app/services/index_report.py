"""
Build the full commodity-index detail payload from a snapshot DataFrame.

Pure orchestration over the indicator/risk services — no ORM, FastAPI or
requests. Importable by both the API (read path) and the worker (cache warm),
so the heavy compute lives in exactly one place.
"""
from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from . import indicators, risk
from ._numeric import clean, series


def compute_index_payload(df: pd.DataFrame, key: str, label: str, kind: str, window: int) -> dict:
    """``df`` columns: timestamp, price, volume, top3_share, h_index, entropy, liquidity."""
    win = max(2, int(window))
    price = df["price"].astype(float)

    ind = indicators.compute(price, win)

    # ── headline stats ──
    last24 = df[df["timestamp"] >= df["timestamp"].max() - pd.Timedelta(hours=24)]
    last = float(price.iloc[-1])
    prev = float(price.iloc[-2]) if len(price) > 1 else last
    stats = {
        "last": clean(last),
        "change_pct": clean((last - prev) / prev * 100 if prev else None),
        "today_max": clean(last24["price"].max()),
        "today_min": clean(last24["price"].min()),
        "today_avg": clean(last24["price"].mean()),
        "all_max": clean(price.max()),
        "all_min": clean(price.min()),
        "all_avg": clean(price.mean()),
        "volatility": clean(ind.volatility.iloc[-1]),
        "liquidity": clean(df["liquidity"].iloc[-1]),
        "entropy": clean(df["entropy"].iloc[-1]),
        "top3_share": clean(df["top3_share"].iloc[-1]),
        "points": int(len(df)),
    }

    # ── risk + market-state analytics ──
    var = risk.value_at_risk(ind.returns)
    montecarlo = risk.monte_carlo_gbm(ind.returns, last)
    heat = risk.volume_heatmap(df)
    states = risk.volatility_regimes(ind.volatility)

    return {
        "key": key,
        "label": label,
        "kind": kind,
        "window": win,
        "timestamps": [t.isoformat() for t in df["timestamp"]],
        "series": {
            "price": series(price), "volume": series(df["volume"]),
            "sma": series(ind.sma), "bb_upper": series(ind.bb_upper), "bb_lower": series(ind.bb_lower),
            "rsi": series(ind.rsi), "macd": series(ind.macd), "macd_signal": series(ind.macd_signal),
            "macd_hist": series(ind.macd_hist),
            "returns": series(ind.returns), "volatility": series(ind.volatility),
            "tenkan": series(ind.tenkan), "kijun": series(ind.kijun),
            "senkou_a": series(ind.senkou_a), "senkou_b": series(ind.senkou_b),
        },
        "stats": stats,
        "risk": {"var95": clean(var.var95), "cvar95": clean(var.cvar95),
                 "hist_counts": var.hist_counts, "hist_edges": var.hist_edges},
        "montecarlo": asdict(montecarlo) if montecarlo else None,
        "heatmap": heat,
        "states": asdict(states) if states else None,
    }
