"""
  GET /market/type/{type_id}                  header: name, icon, breadcrumb
  GET /market/orders?region_id&type_id        Sellers / Buyers tables
  GET /market/orderbook?region_id&type_id     depth ladder (стакан)
  GET /market/history?region_id&type_id&window  technical + risk analytics
  GET /market/correlation?region_id&type_id   return-correlation matrix

"""
from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.adapters import market
from app.core.database import get_db, UserDB
from app.core.database_eve import EveSessionLocal
from app.core.security import get_current_user
from app.repositories import cache_repo, eve_market
from app.services import market_browser

router = APIRouter()

ICON_URL = "https://images.evetech.net/types/{}/icon?size=64"
_HIST_CACHE_TTL = 6 * 3600

REFERENCE_TYPES = [34, 35, 1230, 16273, 16634, 44992]
JITA_REGION = 10000002


def _get_eve_db():
    db = EveSessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/type/{type_id}")
async def type_header(
        type_id: int,
        current_user: UserDB = Depends(get_current_user),
        eve_db: Session = Depends(_get_eve_db),
):
    """Item header: name, group, icon and market-group breadcrumb."""
    info = eve_market.type_info(eve_db, type_id)
    if not info:
        raise HTTPException(404, "Unknown type — is the SDE synced?")
    info["icon_url"] = ICON_URL.format(type_id)
    info["breadcrumb"] = eve_market.market_group_path(eve_db, info.get("market_group_id"))
    return info


def _resolve_locations(eve_db, orders: list[dict]):
    """Batch-resolve every station / system / region referenced by the orders."""
    loc_ids = {o.get("location_id") for o in orders if o.get("location_id")}
    sys_ids = {o.get("system_id") for o in orders if o.get("system_id")}
    stations = eve_market.stations(eve_db, list(loc_ids))
    sys_ids |= {s["system_id"] for s in stations.values() if s.get("system_id")}
    systems = eve_market.systems(eve_db, list(sys_ids))
    region_ids = {s["region_id"] for s in stations.values() if s.get("region_id")}
    region_ids |= {s["region_id"] for s in systems.values() if s.get("region_id")}
    regions = eve_market.regions(eve_db, list(region_ids))
    return stations, systems, regions


@router.get("/orders")
async def orders(
        region_id: int = Query(...),
        type_id: int = Query(...),
        current_user: UserDB = Depends(get_current_user),
        eve_db: Session = Depends(_get_eve_db),
):
    """Sellers / Buyers tables for (region, type) from live ESI orders."""
    raw = market.esi_region_orders(region_id, type_id)
    stations, systems, regions = _resolve_locations(eve_db, raw)
    payload = market_browser.build_orders(
        raw, stations, systems, regions, eve_market.region_name(eve_db, region_id))
    payload["region_id"] = region_id
    payload["type_id"] = type_id
    payload["count"] = len(raw)
    return payload


@router.get("/orderbook")
async def orderbook(
        region_id: int = Query(...),
        type_id: int = Query(...),
        depth: int = Query(60, le=200),
        current_user: UserDB = Depends(get_current_user),
):
    """Aggregated price-level depth ladder for the professional order-book view."""
    raw = market.esi_region_orders(region_id, type_id)
    payload = market_browser.build_orderbook(raw, depth=depth)
    payload["region_id"] = region_id
    payload["type_id"] = type_id
    return payload


@router.get("/history")
async def history(
        region_id: int = Query(...),
        type_id: int = Query(...),
        window: int = Query(10),
        refresh: bool = False,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
        eve_db: Session = Depends(_get_eve_db),
):
    """Technical + risk analytics over the full ESI daily history for (region, type)."""
    win = max(2, int(window))
    cache_key = f"{region_id}:{type_id}"
    if not refresh:
        cached = cache_repo.get_cached(db, "market", cache_key, win, max_age_seconds=_HIST_CACHE_TTL)
        if cached is not None:
            return cached

    rows = market.esi_region_history_full(region_id, type_id)
    if not rows:
        info = eve_market.type_info(eve_db, type_id)
        label = info["type_name"] if info else str(type_id)
        return {"type_id": type_id, "label": label, "region_id": region_id, "empty": True}

    info = eve_market.type_info(eve_db, type_id)
    label = info["type_name"] if info else str(type_id)
    payload = market_browser.history_payload(
        rows, type_id, label, eve_market.region_name(eve_db, region_id), win)
    payload["region_id"] = region_id
    cache_repo.set_cached(db, "market", cache_key, win, payload)
    return payload


@router.get("/correlation")
async def correlation(
        region_id: int = Query(...),
        type_id: int = Query(...),
        current_user: UserDB = Depends(get_current_user),
        eve_db: Session = Depends(_get_eve_db),
):
    info = eve_market.type_info(eve_db, type_id)
    if not info:
        raise HTTPException(404, "Unknown type — is the SDE synced?")
    target_label = info["type_name"]

    peers = eve_market.group_members(eve_db, info.get("group_id"), type_id, limit=6)
    ref_names = eve_market.types_info(eve_db, REFERENCE_TYPES)

    # (label, region_id, type_id) fetch plan — dedupe by label.
    plan: list[tuple[str, int, int]] = [(target_label, region_id, type_id)]
    for p in peers:
        plan.append((p["type_name"], region_id, p["type_id"]))
    for tid in REFERENCE_TYPES:
        if tid == type_id:
            continue
        name = ref_names.get(tid, {}).get("type_name", str(tid))
        plan.append((f"{name} (Jita)", JITA_REGION, tid))

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = await asyncio.gather(*[
            loop.run_in_executor(ex, market.esi_region_history_full, rid, tid)
            for _, rid, tid in plan
        ])

    histories = {label: hist for (label, _, _), hist in zip(plan, results)}
    payload = market_browser.correlation_payload(target_label, histories)
    payload["region_id"] = region_id
    payload["type_id"] = type_id
    return payload
