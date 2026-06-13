import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import requests as _requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database_eve import EveSessionLocal, EveSolarSystem, EveType
from app.core.database import UserDB
from app.core.security import get_current_user

router = APIRouter()


def _get_eve_db():
    db = EveSessionLocal()
    try:
        yield db
    finally:
        db.close()


class SystemOut(BaseModel):
    solar_system_id: int
    solar_system_name: str
    security: Optional[float]
    region_id: Optional[int]

    class Config:
        from_attributes = True


class TypeOut(BaseModel):
    type_id: int
    type_name: str
    volume: Optional[float]
    portion_size: Optional[int]
    market_group_id: Optional[int]

    class Config:
        from_attributes = True


# ── EVE SDE status + trigger ──────────────────────────────────────────

@router.get("/sde/status")
async def sde_status(eve_db: Session = Depends(_get_eve_db)):
    """Return how many types are in the SDE DB (0 means not yet synced)."""
    count = eve_db.query(EveType).count()
    return {"synced": count > 0, "type_count": count}


@router.post("/sde/update")
async def trigger_sde_update(
    current_user: UserDB = Depends(get_current_user),
):
    """Kick off an SDE update in a background thread."""
    import threading
    from app.tasks.update_sde import run_sde_update

    t = threading.Thread(target=run_sde_update, kwargs={"force": True}, daemon=True)
    t.start()
    return {"status": "started", "message": "SDE sync started — takes 5-15 minutes, page will work once complete"}


# ── System / Type search ──────────────────────────────────────────────

@router.get("/systems", response_model=list[SystemOut])
async def search_systems(
    q: str = Query(..., min_length=2),
    limit: int = Query(15, le=50),
    eve_db: Session = Depends(_get_eve_db),
):
    return (
        eve_db.query(EveSolarSystem)
        .filter(EveSolarSystem.solar_system_name.ilike(f"{q}%"))
        .order_by(EveSolarSystem.solar_system_name)
        .limit(limit)
        .all()
    )


@router.get("/types/search", response_model=list[TypeOut])
async def search_types(
    q: str = Query(..., min_length=2),
    limit: int = Query(10, le=30),
    eve_db: Session = Depends(_get_eve_db),
):
    return (
        eve_db.query(EveType)
        .filter(EveType.type_name.ilike(f"%{q}%"))
        .order_by(EveType.type_name)
        .limit(limit)
        .all()
    )


# ── C-J prices via appraise.gnf.lt ───────────────────────────────────

_GNF_REGION = "C-J6MT"
_GNF_HEADERS = {"User-Agent": "IndyOps/1.0 (industrial manager)"}


def _fetch_gnf_price(type_id: int) -> Optional[dict]:
    """Scrape one type_id from appraise.gnf.lt. Returns {buy, sell, split} or None."""
    try:
        url = f"https://appraise.gnf.lt/item/{type_id}"
        resp = _requests.get(url, timeout=15, headers=_GNF_HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        tab = soup.find("div", id=_GNF_REGION)
        if not tab:
            return None

        tables = tab.find_all("table")
        if len(tables) < 2:
            return None

        def parse_table(table):
            out = {}
            for row in table.find_all("tr"):
                th, td = row.find("th"), row.find("td")
                if th and td:
                    raw = td.text.strip().replace(",", "").replace(" ISK", "")
                    try:
                        out[th.text.strip()] = float(raw)
                    except ValueError:
                        pass
            return out

        sell_data = parse_table(tables[0])   # sell orders
        buy_data  = parse_table(tables[1])   # buy orders

        # CSV shows keys: Sell_Min, Buy_Max — HTML strips the prefix
        sell = sell_data.get("Min") or sell_data.get("1st Percentile")
        buy  = buy_data.get("Max")  or buy_data.get("99th Percentile")

        if sell is None or buy is None:
            return None

        return {
            "buy":   round(buy, 2),
            "sell":  round(sell, 2),
            "split": round((buy + sell) / 2, 2),
        }
    except Exception:
        return None


@router.get("/prices/cj")
async def get_cj_prices(
    type_ids: str = Query(..., description="Comma-separated EVE type IDs"),
):
    """Fetch C-J6MT local market prices from appraise.gnf.lt (parallel, max 8 workers)."""
    ids = [int(t.strip()) for t in type_ids.split(",") if t.strip().isdigit()]
    if not ids:
        raise HTTPException(400, "No valid type_ids provided")

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=8) as ex:
        prices = await asyncio.gather(
            *[loop.run_in_executor(ex, _fetch_gnf_price, tid) for tid in ids]
        )

    return {tid: p for tid, p in zip(ids, prices) if p is not None}
