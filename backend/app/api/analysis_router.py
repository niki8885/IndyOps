"""
Commodity-index analytics: technical indicators, risk (VaR/CVaR/Monte Carlo),
volume heatmap and volatility-regime market states. Data comes from the hourly
MarketIndexSnapshot collector.

The heavy lifting lives in the pure service layer (app.services.indicators /
risk / _numeric); this router only loads snapshots and shapes the response.
"""
from dataclasses import asdict

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db, MarketIndexSnapshot, UserDB
from app.core.indices_data import INDEX_META, INDEX_ORDER
from app.core.security import get_current_user
from app.services import indicators, risk
from app.services._numeric import clean, series
from app.tasks.update_indices import run_index_update

router = APIRouter()


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
            "last_price": clean(last.price_index) if last else None,
            "last_volume": clean(last.volume_index) if last else None,
            "change_pct": clean(change),
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

    # ── technical indicators (shared service) ──
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

    # ── risk + market-state analytics (shared service) ──
    var = risk.value_at_risk(ind.returns)
    montecarlo = risk.monte_carlo_gbm(ind.returns, last)
    heat = risk.volume_heatmap(df)
    states = risk.volatility_regimes(ind.volatility)

    return {
        "key": key,
        "label": INDEX_META[key]["label"],
        "kind": INDEX_META[key]["kind"],
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
