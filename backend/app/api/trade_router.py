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
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters import portfolio as portfolio_engine
from app.core import config
from app.core.database import get_db, UserDB, TradeCandidate, StationTradeCandidate
from app.core.security import get_current_user
from app.core.trade_data import HUBS, HUB_STATION_IDS, STATION_TO_HUB
from app.repositories import trade_repo
from app.services import trade
from app.services import portfolio as portfolio_svc

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


# ── portfolio optimizer (Markowitz over cross-hub candidates) ──────────────────

class TradePortfolioRequest(BaseModel):
    budget: float = 0.0                     # target ISK to deploy
    buy_hubs: Optional[str] = None          # CSV hub names (same filters as /candidates)
    sell_hubs: Optional[str] = None
    strategy: str = "patient"               # patient | instant
    min_margin: float = 0.0
    cargo: Optional[float] = None           # cargo m³ ceiling per unit (excludes bulky)
    min_volume: float = 0.0                 # drop items below this daily traded volume
    type_ids: list[int] = []                # optional explicit selection (else whole pool)
    pool_limit: int = 150                   # candidate pool size to optimise over
    risk_aversion: Optional[float] = None   # Markowitz λ (default from config)
    horizon_days: Optional[int] = None      # sell-through horizon for the liquidity cap
    max_weight: Optional[float] = None      # max budget share per item, 0..1
    participation: Optional[float] = None   # fraction of daily volume capturable, 0..1


@router.post("/portfolio")
async def trade_portfolio(body: TradePortfolioRequest,
                          current_user: UserDB = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """Markowitz mean-variance allocation of an ISK budget across the optimizer's
    cross-hub candidates — the same engine as the Jita → C-J haul portfolio. Picks the
    best route per item under the current filters, then water-fills the budget into
    integer buys bounded by liquidity (``participation·daily_volume·horizon``) and
    diversification (``max_weight``) caps. Deterministic native engine, Python fallback."""
    lam = body.risk_aversion if body.risk_aversion is not None else config.TRADE_PORTFOLIO_RISK_AVERSION
    horizon = body.horizon_days or config.TRADE_PORTFOLIO_HORIZON_DAYS
    participation = (body.participation if body.participation is not None
                     else config.TRADE_PORTFOLIO_PARTICIPATION)
    max_weight = body.max_weight if body.max_weight is not None else config.TRADE_PORTFOLIO_MAX_WEIGHT
    instant = body.strategy == "instant"
    want = {int(t) for t in (body.type_ids or [])}

    rows = trade_repo.query_candidates(
        db,
        buy_stations=_stations_for(body.buy_hubs),
        sell_stations=_stations_for(body.sell_hubs),
        max_buy_price=(body.budget or None), max_volume=body.cargo,
        min_margin=body.min_margin, strategy=body.strategy, limit=max(body.pool_limit, 1),
    )

    # cross-hub rows repeat an item across hub pairs → keep the most profitable route per item
    best_by_item: dict[int, dict] = {}
    for r in rows:
        if want and r.item_id not in want:
            continue
        if body.min_volume and (r.daily_volume or 0.0) < body.min_volume:
            continue
        profit = r.profit_isk_instant if instant else r.profit_isk_patient
        cap = r.buy_price or 0.0
        if cap <= 0 or (profit or 0.0) <= 0:
            continue
        cur = best_by_item.get(r.item_id)
        if cur is None or profit > cur["unit_profit"]:
            sigma = max((r.volatility_cv or 0.0) or config.TRADE_PORTFOLIO_DEFAULT_SIGMA,
                        config.TRADE_PORTFOLIO_MIN_SIGMA)
            best_by_item[r.item_id] = {
                "type_id": r.item_id, "name": r.type_name, "category_id": None,
                "unit_cost": cap, "unit_profit": profit, "roi": profit / cap,
                "sigma": sigma, "unit_vol_m3": r.item_volume_m3 or 0.0,
                "daily_volume": r.daily_volume,
                "best_method": (f"{STATION_TO_HUB.get(r.buy_hub, r.buy_hub)} → "
                                f"{STATION_TO_HUB.get(r.sell_hub, r.sell_hub)}"),
            }
    assets = list(best_by_item.values())

    if assets:
        mu_v = [a["roi"] for a in assets]
        sig_v = [a["sigma"] for a in assets]
        weights, _metrics, engine = portfolio_engine.optimize_weights(mu_v, sig_v, lam)
        result = portfolio_svc.build_portfolio(
            assets, weights, body.budget, horizon_days=horizon,
            participation=participation, max_weight=max_weight)
        t = result["totals"]
        result["frontier"] = {
            "points": portfolio_svc.efficient_frontier(mu_v, sig_v),
            "chosen": {"risk_aversion": lam, "stddev": t["stddev"], "exp_return": t["exp_return"]},
            "assets": [{"name": a["name"], "stddev": a["sigma"], "exp_return": a["roi"]} for a in assets],
        }
    else:
        engine = "python"
        result = {"allocations": [], "frontier": None, "totals": {
            "budget": round(max(body.budget or 0.0, 0.0), 2), "capital_used": 0.0, "leftover": 0.0,
            "expected_profit": 0.0, "portfolio_roi": 0.0, "total_volume_m3": 0.0,
            "stddev": 0.0, "exp_return": 0.0, "n_assets": 0, "n_considered": 0}}

    meta = {
        "strategy": body.strategy, "budget": round(max(body.budget or 0.0, 0.0), 2),
        "risk_aversion": lam, "horizon_days": horizon, "participation": participation,
        "max_weight": max_weight, "engine": engine, "n_considered": len(assets),
    }
    return {"meta": meta, "result": result}
