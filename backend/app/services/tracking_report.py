"""
Build the tracked-item detail payload from a track_prices DataFrame.

Pure over plain inputs (item/places dicts + a DataFrame) — no ORM/FastAPI — so
it's unit-testable and callable by both the API (read path) and a cache warmer.
"""
from __future__ import annotations

import pandas as pd

from .indicators import compute as compute_indicators
from .risk import histogram
from ._numeric import clean, series


def build_item_detail(item: dict, places: dict, tp_df: pd.DataFrame,
                      place_ids: list, place_id, window: int) -> dict:
    """
    item   = {"id", "type_id", "name"}
    places = {place_id: {"name", "kind", "special"}}
    tp_df  = columns [timestamp, place_id, buy, sell, volume], oldest-first
    """
    win = max(2, int(window))

    series_by_place, places_meta = {}, []
    for pid in (place_ids or []):
        p = places.get(pid)
        if not p:
            continue
        sub = tp_df[tp_df["place_id"] == pid] if not tp_df.empty else tp_df
        series_by_place[pid] = {
            "timestamps": [t.isoformat() for t in sub["timestamp"]],
            "buy": [clean(v) for v in sub["buy"]],
            "sell": [clean(v) for v in sub["sell"]],
            "volume": [clean(v) for v in sub["volume"]],
        }
        last = sub.iloc[-1] if len(sub) else None
        places_meta.append({
            "place_id": pid, "name": p["name"], "kind": p["kind"], "special": p["special"],
            "latest_buy": clean(last["buy"]) if last is not None else None,
            "latest_sell": clean(last["sell"]) if last is not None else None,
            "latest_volume": clean(last["volume"]) if last is not None else None,
            "points": len(sub),
        })

    # choose a place for indicators: the requested one, else the first with data
    sel = place_id if place_id in series_by_place else next(
        (pid for pid in series_by_place if series_by_place[pid]["timestamps"]), None)

    indicators, distribution, spread = None, None, None
    if sel is not None:
        s = series_by_place[sel]
        df = pd.DataFrame({"ts": s["timestamps"], "buy": s["buy"], "sell": s["sell"]})
        if len(df):
            buy = pd.to_numeric(df["buy"], errors="coerce")
            sell = pd.to_numeric(df["sell"], errors="coerce")
            mid = pd.concat([buy, sell], axis=1).mean(axis=1)
            ind = compute_indicators(mid, window)

            indicators = {
                "timestamps": s["timestamps"],
                "buy": series(buy), "sell": series(sell), "mid": series(mid),
                "sma": series(ind.sma), "ema": series(ind.ema),
                "bb_upper": series(ind.bb_upper), "bb_lower": series(ind.bb_lower),
                "rsi": series(ind.rsi), "macd": series(ind.macd), "macd_signal": series(ind.macd_signal),
                "macd_hist": series(ind.macd_hist),
                "tenkan": series(ind.tenkan), "kijun": series(ind.kijun),
                "senkou_a": series(ind.senkou_a), "senkou_b": series(ind.senkou_b),
            }
            counts, edges = histogram(mid, min_bins=8)
            if counts is not None:
                distribution = {"counts": counts, "edges": edges}
            lb = clean(buy.iloc[-1])
            ls = clean(sell.iloc[-1])
            if lb and ls:
                spread = {"buy": lb, "sell": ls, "abs": round(ls - lb, 2),
                          "pct": round((ls - lb) / ls * 100, 2) if ls else None}

    return {
        "item": item,
        "places": places_meta,
        "series_by_place": series_by_place,
        "selected_place_id": sel,
        "window": win,
        "indicators": indicators,
        "distribution": distribution,
        "spread": spread,
    }
