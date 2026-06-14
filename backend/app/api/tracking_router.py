from dataclasses import asdict
from typing import Optional, List
import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.adapters import market
from app.core.database import get_db, UserDB, TrackedPlace, TrackedItem
from app.core.database_eve import EveSessionLocal
from app.core.security import get_current_user
from app.repositories import cache_repo, eve as eve_repo, market_repo
from app.services import allocation, tracking_report
from app.tasks.update_tracking import collect_for_user

router = APIRouter()

MAX_PLACES = 5
MAX_ITEMS = 100
_CACHE_TTL = 3600   # serve cached item detail for up to an hour (the collector cadence)


def _hist_stats(rows: Optional[list]) -> dict:
    if not rows:
        return {"avg": None, "min": None, "max": None, "vol": None}
    avg = float(np.mean([d["average"] for d in rows]))
    lo = float(min(d["lowest"] for d in rows))
    hi = float(max(d["highest"] for d in rows))
    vol = float(np.mean([d["volume"] for d in rows]))
    return {"avg": round(avg, 2), "min": round(lo, 2), "max": round(hi, 2), "vol": round(vol, 0)}


# ── schemas ──
class PlaceCreate(BaseModel):
    kind: str  # system | region
    name: str
    region_id: Optional[int] = None
    solar_system_id: Optional[int] = None
    special_parser: bool = False


class PlaceOut(BaseModel):
    id: int
    kind: str
    name: str
    region_id: Optional[int]
    solar_system_id: Optional[int]
    special_parser: bool

    class Config:
        from_attributes = True


class ItemCreate(BaseModel):
    type_id: int
    name: str
    place_ids: List[int] = []


class ItemUpdate(BaseModel):
    place_ids: Optional[List[int]] = None


class ItemOut(BaseModel):
    id: int
    type_id: int
    name: str
    place_ids: Optional[List[int]]

    class Config:
        from_attributes = True


# ── places ──
@router.get("/places", response_model=List[PlaceOut])
async def list_places(current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(TrackedPlace).filter(TrackedPlace.user_id == current_user.id).order_by(TrackedPlace.name).all()


@router.post("/places", response_model=PlaceOut, status_code=201)
async def add_place(body: PlaceCreate, current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    count = db.query(TrackedPlace).filter(TrackedPlace.user_id == current_user.id).count()
    if count >= MAX_PLACES:
        raise HTTPException(400, f"Max {MAX_PLACES} places")
    p = TrackedPlace(user_id=current_user.id, **body.model_dump())
    db.add(p);
    db.commit();
    db.refresh(p)
    return p


@router.delete("/places/{place_id}", status_code=204)
async def del_place(place_id: int, current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    p = db.query(TrackedPlace).filter(TrackedPlace.id == place_id, TrackedPlace.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "Place not found")
    db.delete(p);
    db.commit()


# ── items ──
@router.get("/items", response_model=List[ItemOut])
async def list_items(current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(TrackedItem).filter(TrackedItem.user_id == current_user.id).order_by(TrackedItem.name).all()


@router.post("/items", response_model=ItemOut, status_code=201)
async def add_item(body: ItemCreate, current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    count = db.query(TrackedItem).filter(TrackedItem.user_id == current_user.id).count()
    if count >= MAX_ITEMS:
        raise HTTPException(400, f"Max {MAX_ITEMS} items")
    existing = db.query(TrackedItem).filter(
        TrackedItem.user_id == current_user.id, TrackedItem.type_id == body.type_id
    ).first()
    if existing:
        raise HTTPException(400, "Item already tracked")
    it = TrackedItem(user_id=current_user.id, type_id=body.type_id, name=body.name, place_ids=body.place_ids)
    db.add(it);
    db.commit();
    db.refresh(it)
    return it


@router.patch("/items/{item_id}", response_model=ItemOut)
async def update_item(item_id: int, body: ItemUpdate, current_user: UserDB = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    it = db.query(TrackedItem).filter(TrackedItem.id == item_id, TrackedItem.user_id == current_user.id).first()
    if not it:
        raise HTTPException(404, "Item not found")
    if body.place_ids is not None:
        it.place_ids = body.place_ids
    db.commit();
    db.refresh(it)
    return it


@router.delete("/items/{item_id}", status_code=204)
async def del_item(item_id: int, current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    it = db.query(TrackedItem).filter(TrackedItem.id == item_id, TrackedItem.user_id == current_user.id).first()
    if not it:
        raise HTTPException(404, "Item not found")
    db.delete(it);
    db.commit()


@router.post("/refresh")
async def refresh_now(current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = collect_for_user(db, current_user.id)
    return {"stored": rows}


# ── detail + indicators ──
@router.get("/item/{item_id}")
async def item_detail(
        item_id: int,
        place_id: Optional[int] = None,
        window: int = 10,
        refresh: bool = False,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    it = db.query(TrackedItem).filter(TrackedItem.id == item_id, TrackedItem.user_id == current_user.id).first()
    if not it:
        raise HTTPException(404, "Item not found")

    win = max(2, int(window))
    cache_key = f"{item_id}:{place_id if place_id is not None else 'auto'}"
    if not refresh:
        cached = cache_repo.get_cached(db, "tracking", cache_key, win, max_age_seconds=_CACHE_TTL)
        if cached is not None:
            return cached

    places = {
        p.id: {"name": p.name, "kind": p.kind, "special": p.special_parser}
        for p in db.query(TrackedPlace).filter(TrackedPlace.user_id == current_user.id).all()
    }
    tp = market_repo.track_prices_df(db, current_user.id, it.type_id)   # columnar, not row-ORM

    payload = tracking_report.build_item_detail(
        {"id": it.id, "type_id": it.type_id, "name": it.name},
        places, tp, it.place_ids, place_id, window)
    cache_repo.set_cached(db, "tracking", cache_key, win, payload)
    return payload


# ── Warehouse allocation / sell-decision ──
class AllocItem(BaseModel):
    type_id: int
    name: str
    quantity: int
    cost: Optional[float] = None  # cost basis per unit (for profit)


class AllocateRequest(BaseModel):
    items: List[AllocItem]
    place_ids: List[int]
    strategy: str = "balanced"  # fast | balanced | maxprofit
    fees_pct: float = 8.0  # broker + tax on sell orders
    delivery_coef: float = 1200.0  # ISK/m³
    delivery_place_ids: List[int] = []
    balance_days: int = 7


def _current_prices(place: TrackedPlace, type_id: int) -> dict:
    """Live buy/sell for a place."""
    if place.special_parser:
        d = market.gnf_local(type_id) or {}
        return {"buy": d.get("buy"), "sell": d.get("sell")}
    e = (market.fuzzwork_aggregates_or_empty(place.region_id, [type_id]) or {}).get(str(type_id)) or {}

    def f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {"buy": f((e.get("buy") or {}).get("max")), "sell": f((e.get("sell") or {}).get("min"))}


@router.post("/allocate")
async def allocate(
        body: AllocateRequest,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    places = {p.id: p for p in db.query(TrackedPlace).filter(
        TrackedPlace.user_id == current_user.id, TrackedPlace.id.in_(body.place_ids or [-1])).all()}
    if not places:
        raise HTTPException(400, "Select at least one favourite place")

    # volumes for delivery
    eve_db = EveSessionLocal()
    try:
        vol_map = eve_repo.volumes(eve_db, [i.type_id for i in body.items])
    finally:
        eve_db.close()

    fees = body.fees_pct / 100.0
    out_items = []
    for it in body.items:
        unit_vol = vol_map.get(it.type_id) or 0
        venues = []
        for pid, p in places.items():
            cur = _current_prices(p, it.type_id)
            hist = _hist_stats(market.esi_region_history(p.region_id, it.type_id)) if p.region_id else {"avg": None,
                                                                                                        "min": None,
                                                                                                        "max": None,
                                                                                                        "vol": None}
            delivery_unit = (body.delivery_coef * unit_vol) if pid in body.delivery_place_ids else 0.0
            buy, sell = cur["buy"], cur["sell"]
            venues.append({
                "place_id": pid, "place_name": p.name, "special": p.special_parser,
                "buy": buy, "sell": sell,
                "delivery_unit": round(delivery_unit, 2),
                "net_instant": round((buy or 0) - delivery_unit, 2) if buy else None,
                "net_patient": round((sell or 0) * (1 - fees) - delivery_unit, 2) if sell else None,
                "hist": hist,
            })

        # hold / sell signal: best current sell vs its 30d average
        best = max((v for v in venues if v["sell"]), key=lambda v: v["sell"], default=None)
        signal = "neutral"
        if best and best["hist"]["avg"]:
            ratio = best["sell"] / best["hist"]["avg"]
            signal = "sell" if ratio >= 1.0 else ("hold" if ratio < 0.9 else "neutral")

        svc_venues = [
            allocation.Venue(v["place_id"], v["place_name"], v["net_instant"], v["net_patient"], v["hist"]["vol"])
            for v in venues
        ]
        allocations = [asdict(a) for a in
                       allocation.allocate(svc_venues, it.quantity, body.strategy, body.balance_days)]
        total_net = round(sum(a["net_total"] for a in allocations), 2)
        total_profit = round(total_net - (it.cost or 0) * it.quantity, 2) if it.cost else None
        out_items.append({
            "type_id": it.type_id, "name": it.name, "quantity": it.quantity, "cost": it.cost,
            "signal": signal, "venues": venues, "allocations": allocations,
            "total_net": total_net, "total_profit": total_profit,
        })

    return {"strategy": body.strategy, "items": out_items}
