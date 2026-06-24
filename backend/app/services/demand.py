"""Demand metrics for one (region, type) — descriptive, model-free (IO-49 phase 1).

Pure service: takes raw ESI daily history rows + an aggregated order book and
returns a JSON-safe payload describing *demand*, the gap the price-centric
``history_payload`` left open. Throughput, trend/momentum, weekday seasonality,
demand volatility and live order-book pressure, plus a transparent 0-100 score.
"""
from __future__ import annotations
from typing import Optional

import numpy as np
import pandas as pd

from ._numeric import clean, series
from .market_browser import _history_frame


def _tail_mean(s: pd.Series, days: int) -> Optional[float]:
    tail = s.tail(days).dropna()
    return float(tail.mean()) if len(tail) else None


def _trend_slope(vol: pd.Series) -> Optional[float]:
    """OLS slope of log1p(volume) vs day index → relative growth per day."""
    v = vol.fillna(0).astype(float).values
    if len(v) < 5:
        return None
    y = np.log1p(v)
    x = np.arange(len(y), dtype=float)
    if np.ptp(y) == 0:
        return 0.0
    return float(np.polyfit(x, y, 1)[0])


def _trend_line(vol: pd.Series) -> list:
    """Fitted volume trend (expm1 of the log-fit) aligned with the series."""
    v = vol.fillna(0).astype(float).values
    if len(v) < 5:
        return [None] * len(v)
    y = np.log1p(v)
    x = np.arange(len(y), dtype=float)
    a, b = np.polyfit(x, y, 1)
    return [clean(z) for z in np.expm1(a * x + b)]


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def demand_payload(history: list[dict], type_id: int, label: str,
                   region_name: Optional[str], book: Optional[dict]) -> dict:
    """Full demand analytics for one type, shaped like the other market payloads."""
    df = _history_frame(history)
    vol = pd.to_numeric(df["volume"], errors="coerce")
    price = df["price"]
    oc = pd.to_numeric(df["order_count"], errors="coerce")
    turnover = vol * price                       # ISK changing hands per day
    n = len(df)

    adv7, adv30, adv90 = _tail_mean(vol, 7), _tail_mean(vol, 30), _tail_mean(vol, 90)
    # prior 30-day window (days 31-60 from the end) for the 30d trend delta
    prev30 = vol.iloc[-60:-30] if n >= 60 else pd.Series(dtype=float)
    prev30_mean = float(prev30.mean()) if len(prev30) else None
    last90 = vol.tail(90)
    active_ratio = float((last90 > 0).mean()) if len(last90) else None
    isk_per_day = _tail_mean(turnover, 30)

    vol30 = vol.tail(30).dropna()
    vol_cv = float(vol30.std() / vol30.mean()) if len(vol30) > 1 and vol30.mean() else None
    last_vol = float(vol.iloc[-1]) if n else None
    spike_z = (float((last_vol - vol30.mean()) / vol30.std())
               if (last_vol is not None and len(vol30) > 1 and vol30.std()) else None)

    slope = _trend_slope(vol)
    trend_pct_30 = ((adv30 / prev30_mean - 1.0)
                    if (adv30 is not None and prev30_mean) else None)
    momentum = (adv7 / adv30) if (adv7 is not None and adv30) else None

    # weekday seasonality (volume mean per UTC weekday)
    wd = df.assign(wd=df["timestamp"].dt.weekday, v=vol)
    weekday_volume = [
        clean(wd.loc[wd["wd"] == k, "v"].mean()) if (wd["wd"] == k).any() else None
        for k in range(7)
    ]
    wk = [wd.loc[wd["wd"] == k, "v"].mean() for k in range(5) if (wd["wd"] == k).any()]
    we = [wd.loc[wd["wd"] == k, "v"].mean() for k in (5, 6) if (wd["wd"] == k).any()]
    weekend_lift = (float(np.nanmean(we) / np.nanmean(wk))
                    if wk and we and np.nanmean(wk) else None)
    weekly_autocorr = (float(vol.fillna(0).autocorr(lag=7))
                       if n >= 14 else None)

    # live order-book pressure (point-in-time snapshot)
    book = book or {}
    bid_depth = book.get("bid_depth") or 0
    ask_depth = book.get("ask_depth") or 0
    best_bid = book.get("best_bid")
    denom = bid_depth + ask_depth
    imbalance = ((bid_depth - ask_depth) / denom) if denom else None
    demand_cov = (bid_depth / adv30) if (adv30 and bid_depth) else None
    supply_cov = (ask_depth / adv30) if (adv30 and ask_depth) else None
    bid_isk = (bid_depth * best_bid) if (best_bid is not None) else None

    # transparent 0-100 demand score (heuristic; batch-ML will refine in phase 3)
    liquidity = _clamp(np.log10((isk_per_day or 0) + 1) / 11.0)   # ~1e11 ISK/day → 1.0
    consistency = active_ratio if active_ratio is not None else 0.0
    trend_norm = _clamp(0.5 + (slope or 0.0) * 10.0)             # ±10%/day → 0..1
    total_score = 100.0 * (0.5 * liquidity + 0.3 * consistency + 0.2 * trend_norm)

    return {
        "type_id": type_id,
        "label": label,
        "region_name": region_name,
        "timestamps": [t.isoformat() for t in df["timestamp"]],
        "series": {
            "volume": series(vol),
            "volume_ma7": series(vol.rolling(7, min_periods=1).mean()),
            "isk_turnover": series(turnover),
            "order_count": series(oc),
            "trend_line": _trend_line(vol),
        },
        "stats": {
            "adv7": clean(adv7), "adv30": clean(adv30), "adv90": clean(adv90),
            "median30": clean(vol.tail(30).median()),
            "isk_per_day": clean(isk_per_day),
            "active_days_ratio": clean(active_ratio),
            "avg_order_count": clean(_tail_mean(oc, 30)),
            "last_volume": clean(last_vol),
            "trend_slope": clean(slope),
            "trend_pct_30": clean(trend_pct_30),
            "momentum": clean(momentum),
            "volume_cv": clean(vol_cv),
            "spike_z": clean(spike_z),
            "points": int(n),
        },
        "book": {
            "best_bid": clean(best_bid),
            "best_ask": clean(book.get("best_ask")),
            "spread": clean(book.get("spread")),
            "spread_pct": clean(book.get("spread_pct")),
            "mid": clean(book.get("mid")),
            "bid_depth": int(bid_depth),
            "ask_depth": int(ask_depth),
            "bid_isk": clean(bid_isk),
            "imbalance": clean(imbalance),
            "demand_coverage_days": clean(demand_cov),
            "supply_coverage_days": clean(supply_cov),
        },
        "weekday_volume": weekday_volume,
        "weekend_lift": clean(weekend_lift),
        "weekly_autocorr": clean(weekly_autocorr),
        "score": {
            "total": clean(total_score),
            "liquidity": clean(liquidity),
            "consistency": clean(consistency),
            "trend": clean(trend_norm),
        },
    }
