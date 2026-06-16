"""
Gather the market history the profit simulator samples from, per type.

I/O lives here (DB reads + ESI), keeping services.profit_sim / market_model pure
(see [[indyops-service-layering]]). Source priority per type:

  1. the user's tracked buy/sell/volume series (richest — both order-book sides),
  2. else ESI region daily history (lowest≈buy, highest≈sell, average mid, volume),
  3. else a degenerate point price (the resolved plan price) → the builder falls
     back to a lognormal around it.

The result feeds services.profit_sim.request_from_chain / request_from_calc.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from app.adapters import market
from app.repositories import market_repo
from app.services.profit_sim import TypeHistory

logger = logging.getLogger(__name__)

_MIN_POINTS = 8   # below this a tracked series is too thin to bootstrap from


def _finite(series) -> list[float]:
    return [float(v) for v in series if pd.notna(v)]


def _from_tracked(df: pd.DataFrame) -> Optional[TypeHistory]:
    """Pick the most-populated place's series (a coherent time-ordered sample)."""
    if df.empty:
        return None
    place = df["place_id"].value_counts().idxmax()
    sub = df[df["place_id"] == place].sort_values("timestamp")
    buy, sell, vol = _finite(sub["buy"]), _finite(sub["sell"]), _finite(sub["volume"])
    if len(buy) < _MIN_POINTS and len(sell) < _MIN_POINTS:
        return None
    return TypeHistory(buy=buy, sell=sell, volume=vol,
                       last_buy=buy[-1] if buy else None,
                       last_sell=sell[-1] if sell else None)


def _from_esi(rows: list) -> Optional[TypeHistory]:
    """ESI daily history → lowest≈buy, highest≈sell, volume. None if unusable."""
    if not rows:
        return None
    low = [float(r["lowest"]) for r in rows if r.get("lowest")]
    high = [float(r["highest"]) for r in rows if r.get("highest")]
    vol = [float(r["volume"]) for r in rows if r.get("volume") is not None]
    if len(low) < _MIN_POINTS:
        return None
    return TypeHistory(buy=low, sell=high or low, volume=vol,
                       last_buy=low[-1] if low else None,
                       last_sell=(high or low)[-1] if (high or low) else None)


def gather_history(db, user_id: int, type_ids: list[int], region_id: int, *,
                   group_of: Optional[dict[int, int]] = None,
                   point_buy: Optional[dict[int, float]] = None,
                   point_sell: Optional[dict[int, float]] = None) -> dict[int, TypeHistory]:
    """Per-type :class:`TypeHistory` for the simulator. ``group_of`` maps a type to a
    market-class id (e.g. SDE category — used by the factor model); ``point_buy`` /
    ``point_sell`` are the resolved single-point prices used as the last-resort
    fallback so every leg is still sampleable."""
    group_of = group_of or {}
    point_buy = point_buy or {}
    point_sell = point_sell or {}
    out: dict[int, TypeHistory] = {}
    for tid in type_ids:
        th: Optional[TypeHistory] = None
        try:
            th = _from_tracked(market_repo.track_prices_df(db, user_id, tid))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("sim_data: tracked history failed for %s: %s", tid, exc)
        if th is None:
            try:
                th = _from_esi(market.esi_region_history(region_id, tid))
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("sim_data: ESI history failed for %s: %s", tid, exc)
        if th is None:
            th = TypeHistory()
        th.group_id = int(group_of.get(tid) or 0)
        if th.last_buy is None:
            th.last_buy = point_buy.get(tid)
        if th.last_sell is None:
            th.last_sell = point_sell.get(tid) or point_buy.get(tid)
        out[tid] = th
    return out
