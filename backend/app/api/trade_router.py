"""
Trade optimizer query API (Layer 3) — a thin, ESI-free read over the
precomputed candidate tables. The worker keeps the tables fresh; here we just
filter by the user's budget / cargo / hubs and rank by margin · volume_score.

The ``updated_at`` / ``stale`` fields report data freshness against
``config.TRADE_TTL_SECONDS`` so the UI can warn — no collection is triggered.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core import config
from app.core.database import get_db, UserDB, TradeCandidate, StationTradeCandidate
from app.core.security import get_current_user
from app.core.trade_data import HUBS, HUB_STATION_IDS, STATION_TO_HUB
from app.repositories import trade_repo
from app.services import trade

router = APIRouter()


def _stations_for(names: Optional[str]) -> Optional[list[int]]:
    """CSV of hub names → station_ids (None if unset → no hub restriction)."""
    if not names:
        return None
    out = [HUB_STATION_IDS[n] for n in (x.strip() for x in names.split(",")) if n in HUB_STATION_IDS]
    return out or None


def _freshness(updated_at) -> tuple[Optional[str], bool]:
    """(iso updated_at, stale?) — a naive stored timestamp is treated as UTC."""
    if updated_at is None:
        return None, True
    ua = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=timezone.utc)
    stale = (datetime.now(timezone.utc) - ua).total_seconds() > config.TRADE_TTL_SECONDS
    return updated_at.isoformat(), stale


@router.get("/hubs")
async def list_hubs(current_user: UserDB = Depends(get_current_user)):
    """The trade hubs the optimizer covers (for the filter UI)."""
    return [{"name": n, "station_id": h["station_id"], "region_id": h["region_id"]}
            for n, h in HUBS.items()]


@router.get("/candidates")
async def list_candidates(
    budget: Optional[float] = Query(None, ge=0, description="ISK capital"),
    cargo: Optional[float] = Query(None, ge=0, description="cargo m³"),
    buy_hubs: Optional[str] = Query(None, description="CSV of hub names to buy from"),
    sell_hubs: Optional[str] = Query(None, description="CSV of hub names to sell at"),
    strategy: str = Query("patient", pattern="^(patient|instant)$"),
    min_margin: float = Query(0.0, description="margin fraction floor, e.g. 0.05"),
    limit: int = Query(50, ge=1, le=500),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ranked cross-hub routes for the given constraints."""
    rows = trade_repo.query_candidates(
        db,
        buy_stations=_stations_for(buy_hubs),
        sell_stations=_stations_for(sell_hubs),
        max_buy_price=budget, max_volume=cargo,
        min_margin=min_margin, strategy=strategy, limit=limit,
    )
    instant = strategy == "instant"
    out = []
    for r in rows:
        margin = r.margin_pct_instant if instant else r.margin_pct_patient
        sell_price = r.sell_price_instant if instant else r.sell_price_patient
        profit = r.profit_isk_instant if instant else r.profit_isk_patient
        plan = trade.plan_trade(r.buy_price, r.item_volume_m3, profit, r.daily_volume, budget, cargo)
        out.append({
            "item_id": r.item_id,
            "type_name": r.type_name,
            "buy_hub": STATION_TO_HUB.get(r.buy_hub, str(r.buy_hub)),
            "sell_hub": STATION_TO_HUB.get(r.sell_hub, str(r.sell_hub)),
            "buy_price": r.buy_price,
            "sell_price": sell_price,
            "margin_pct": margin,
            "profit_isk": profit,
            "transport_cost": r.transport_cost,
            "item_volume_m3": r.item_volume_m3,
            "daily_volume": r.daily_volume,
            "volatility_cv": r.volatility_cv,
            "volume_score": r.volume_score,
            "score": (margin or 0.0) * (r.volume_score or 0.0),
            **plan,
        })
    updated_at, stale = _freshness(trade_repo.latest_updated_at(db, TradeCandidate))
    return {"strategy": strategy, "count": len(out), "updated_at": updated_at,
            "stale": stale, "ttl_seconds": config.TRADE_TTL_SECONDS, "rows": out}


@router.get("/station")
async def list_station_candidates(
    hubs: Optional[str] = Query(None, description="CSV of hub names"),
    budget: Optional[float] = Query(None, ge=0),
    min_margin: float = Query(0.0),
    limit: int = Query(50, ge=1, le=500),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ranked in-station flips (buy order → sell order at the same hub)."""
    rows = trade_repo.query_station_candidates(
        db, stations=_stations_for(hubs), min_margin=min_margin, limit=limit)
    out = []
    for r in rows:
        plan = trade.plan_trade(r.buy_price, None, r.profit_isk, r.daily_volume, budget, None)
        out.append({
            "item_id": r.item_id,
            "type_name": r.type_name,
            "hub": STATION_TO_HUB.get(r.hub, str(r.hub)),
            "buy_price": r.buy_price,
            "sell_price": r.sell_price,
            "margin_pct": r.margin_pct,
            "profit_isk": r.profit_isk,
            "daily_volume": r.daily_volume,
            "volatility_cv": r.volatility_cv,
            "volume_score": r.volume_score,
            "score": (r.margin_pct or 0.0) * (r.volume_score or 0.0),
            **plan,
        })
    updated_at, stale = _freshness(trade_repo.latest_updated_at(db, StationTradeCandidate))
    return {"count": len(out), "updated_at": updated_at, "stale": stale,
            "ttl_seconds": config.TRADE_TTL_SECONDS, "rows": out}
