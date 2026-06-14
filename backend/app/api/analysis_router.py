"""
Commodity-index analytics: technical indicators, risk (VaR/CVaR/Monte Carlo),
volume heatmap and volatility-regime market states. Data comes from the hourly
MarketIndexSnapshot collector.
"""
import math
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_db, MarketIndexSnapshot, UserDB
from app.core.indices_data import INDEX_META, INDEX_ORDER
from app.core.security import get_current_user
from app.tasks.update_indices import run_index_update
from sqlalchemy.orm import Session

router = APIRouter()


def _clean(x):
    """JSON-safe: NaN/inf → None, numpy → python."""
    if x is None:
        return None
    if isinstance(x, (np.floating, float)):
        return None if (math.isnan(x) or math.isinf(x)) else float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    return x


def _series(s: pd.Series):
    return [_clean(v) for v in s.tolist()]


@router.get("/indices")
async def list_indices(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """All indices with a small latest-summary for the overview cards."""
    out = []
    for key in INDEX_ORDER:
        meta = INDEX_META[key]
        rows = (
            db.query(MarketIndexSnapshot)
            .filter(MarketIndexSnapshot.index_key == key)
            .order_by(MarketIndexSnapshot.timestamp.desc())
            .limit(48)
            .all()
        )
        last = rows[0] if rows else None
        prev = rows[1] if len(rows) > 1 else None
        change = None
        if last and prev and prev.price_index:
            change = (last.price_index - prev.price_index) / prev.price_index * 100
        out.append({
            "key": key,
            "label": meta["label"],
            "kind": meta["kind"],
            "last_price": _clean(last.price_index) if last else None,
            "last_volume": _clean(last.volume_index) if last else None,
            "change_pct": _clean(change),
            "points": len(rows),
            "updated_at": last.timestamp.isoformat() if last else None,
        })
    return {"indices": out}


@router.post("/refresh")
async def refresh_now(current_user: UserDB = Depends(get_current_user)):
    """Collect a snapshot immediately (instead of waiting for the hourly job)."""
    return run_index_update()


@router.get("/index/{key}")
async def index_detail(
    key: str,
    window: int = 10,
    days: int = 60,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if key not in INDEX_META:
        raise HTTPException(404, "Unknown index")

    rows = (
        db.query(MarketIndexSnapshot)
        .filter(MarketIndexSnapshot.index_key == key)
        .order_by(MarketIndexSnapshot.timestamp.asc())
        .all()
    )
    if not rows:
        return {"key": key, "label": INDEX_META[key]["label"], "empty": True}

    df = pd.DataFrame([{
        "timestamp": r.timestamp,
        "price": r.price_index,
        "volume": r.volume_index,
        "top3_share": r.top3_share,
        "h_index": r.h_index,
        "entropy": r.entropy,
        "liquidity": r.liquidity_index,
    } for r in rows])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    price = df["price"].astype(float)
    win = max(2, int(window))

    # ── technical indicators ──
    sma = price.rolling(win).mean()
    std = price.rolling(win).std()
    bb_upper = sma + 2 * std
    bb_lower = sma - 2 * std

    returns = price.pct_change()
    volatility = returns.rolling(win).std()

    delta = price.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.rolling(14).mean()
    roll_down = down.rolling(14).mean()
    rs = roll_up / roll_down
    rsi = 100 - (100 / (1 + rs))

    ema12 = price.ewm(span=12, adjust=False).mean()
    ema26 = price.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - macd_signal

    # ichimoku
    high = price.rolling(9).max(); low = price.rolling(9).min()
    tenkan = (high + low) / 2
    high26 = price.rolling(26).max(); low26 = price.rolling(26).min()
    kijun = (high26 + low26) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    high52 = price.rolling(52).max(); low52 = price.rolling(52).min()
    senkou_b = ((high52 + low52) / 2).shift(26)

    # ── headline stats ──
    last24 = df[df["timestamp"] >= df["timestamp"].max() - pd.Timedelta(hours=24)]
    last = float(price.iloc[-1])
    prev = float(price.iloc[-2]) if len(price) > 1 else last
    stats = {
        "last": _clean(last),
        "change_pct": _clean((last - prev) / prev * 100 if prev else None),
        "today_max": _clean(last24["price"].max()),
        "today_min": _clean(last24["price"].min()),
        "today_avg": _clean(last24["price"].mean()),
        "all_max": _clean(price.max()),
        "all_min": _clean(price.min()),
        "all_avg": _clean(price.mean()),
        "volatility": _clean(volatility.iloc[-1]),
        "liquidity": _clean(df["liquidity"].iloc[-1]),
        "entropy": _clean(df["entropy"].iloc[-1]),
        "top3_share": _clean(df["top3_share"].iloc[-1]),
        "points": int(len(df)),
    }

    # ── risk: VaR / CVaR (historical) ──
    rclean = returns.dropna()
    var95 = cvar95 = None
    if len(rclean) >= 5:
        var95 = float(np.percentile(rclean, 5))
        tail = rclean[rclean <= var95]
        cvar95 = float(tail.mean()) if len(tail) else var95
    hist_counts, hist_edges = (None, None)
    if len(rclean) >= 5:
        counts, edges = np.histogram(rclean, bins=min(30, max(10, len(rclean) // 3)))
        hist_counts = counts.tolist()
        hist_edges = [float(e) for e in edges]

    # ── Monte Carlo (GBM) ──
    montecarlo = None
    if len(rclean) >= 10:
        logret = np.log1p(rclean.values)
        mu, sigma = float(np.mean(logret)), float(np.std(logret))
        horizon, n_paths = 24, 500
        rng = np.random.default_rng(42)
        shocks = rng.normal(mu, sigma, size=(n_paths, horizon))
        paths = last * np.exp(np.cumsum(shocks, axis=1))
        montecarlo = {
            "horizon": horizon,
            "p5":  [float(x) for x in np.percentile(paths, 5, axis=0)],
            "p50": [float(x) for x in np.percentile(paths, 50, axis=0)],
            "p95": [float(x) for x in np.percentile(paths, 95, axis=0)],
            "final_p5":  _clean(np.percentile(paths[:, -1], 5)),
            "final_p50": _clean(np.percentile(paths[:, -1], 50)),
            "final_p95": _clean(np.percentile(paths[:, -1], 95)),
        }

    # ── volume heatmap: weekday × hour mean volume ──
    dfh = df.copy()
    dfh["wd"] = dfh["timestamp"].dt.weekday
    dfh["hr"] = dfh["timestamp"].dt.hour
    heat = [[None] * 24 for _ in range(7)]
    if dfh["volume"].notna().any():
        grp = dfh.groupby(["wd", "hr"])["volume"].mean()
        for (wd, hr), v in grp.items():
            heat[int(wd)][int(hr)] = _clean(v)

    # ── market states: volatility-regime terciles ──
    states = None
    vclean = volatility.dropna()
    if len(vclean) >= 6:
        q1, q2 = np.percentile(vclean, [33, 66])
        def regime(v):
            if pd.isna(v): return None
            return 0 if v <= q1 else (1 if v <= q2 else 2)
        labels = [regime(v) for v in volatility]
        cur = next((labels[i] for i in range(len(labels) - 1, -1, -1) if labels[i] is not None), None)
        states = {
            "labels": labels,                       # 0 calm / 1 normal / 2 turbulent
            "names": ["Calm", "Normal", "Turbulent"],
            "current": cur,
            "thresholds": [_clean(q1), _clean(q2)],
            "counts": [int(sum(1 for l in labels if l == k)) for k in range(3)],
        }

    return {
        "key": key,
        "label": INDEX_META[key]["label"],
        "kind": INDEX_META[key]["kind"],
        "window": win,
        "timestamps": [t.isoformat() for t in df["timestamp"]],
        "series": {
            "price": _series(price), "volume": _series(df["volume"]),
            "sma": _series(sma), "bb_upper": _series(bb_upper), "bb_lower": _series(bb_lower),
            "rsi": _series(rsi), "macd": _series(macd), "macd_signal": _series(macd_signal),
            "macd_hist": _series(macd_hist),
            "returns": _series(returns), "volatility": _series(volatility),
            "tenkan": _series(tenkan), "kijun": _series(kijun),
            "senkou_a": _series(senkou_a), "senkou_b": _series(senkou_b),
        },
        "stats": stats,
        "risk": {"var95": _clean(var95), "cvar95": _clean(cvar95),
                 "hist_counts": hist_counts, "hist_edges": hist_edges},
        "montecarlo": montecarlo,
        "heatmap": heat,
        "states": states,
    }
