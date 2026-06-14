"""
Per-user item price tracking — favourite places, tracked items, and a
detail endpoint with technical indicators + cross-place comparison.
"""
import math
from typing import Optional, List

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db, UserDB, TrackedPlace, TrackedItem, TrackPrice
from app.core.security import get_current_user
from app.tasks.update_tracking import collect_for_user

router = APIRouter()

MAX_PLACES = 5
MAX_ITEMS = 100


def _clean(x):
    if x is None:
        return None
    if isinstance(x, (np.floating, float)):
        return None if (math.isnan(x) or math.isinf(x)) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    return x


def _ser(s):
    return [_clean(v) for v in s.tolist()]


# ── schemas ──
class PlaceCreate(BaseModel):
    kind: str                                  # system | region
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
    db.add(p); db.commit(); db.refresh(p)
    return p


@router.delete("/places/{place_id}", status_code=204)
async def del_place(place_id: int, current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    p = db.query(TrackedPlace).filter(TrackedPlace.id == place_id, TrackedPlace.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "Place not found")
    db.delete(p); db.commit()


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
    db.add(it); db.commit(); db.refresh(it)
    return it


@router.patch("/items/{item_id}", response_model=ItemOut)
async def update_item(item_id: int, body: ItemUpdate, current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    it = db.query(TrackedItem).filter(TrackedItem.id == item_id, TrackedItem.user_id == current_user.id).first()
    if not it:
        raise HTTPException(404, "Item not found")
    if body.place_ids is not None:
        it.place_ids = body.place_ids
    db.commit(); db.refresh(it)
    return it


@router.delete("/items/{item_id}", status_code=204)
async def del_item(item_id: int, current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    it = db.query(TrackedItem).filter(TrackedItem.id == item_id, TrackedItem.user_id == current_user.id).first()
    if not it:
        raise HTTPException(404, "Item not found")
    db.delete(it); db.commit()


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
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    it = db.query(TrackedItem).filter(TrackedItem.id == item_id, TrackedItem.user_id == current_user.id).first()
    if not it:
        raise HTTPException(404, "Item not found")

    places = {p.id: p for p in db.query(TrackedPlace).filter(TrackedPlace.user_id == current_user.id).all()}
    rows = (
        db.query(TrackPrice)
        .filter(TrackPrice.user_id == current_user.id, TrackPrice.type_id == it.type_id)
        .order_by(TrackPrice.timestamp.asc())
        .all()
    )

    # per-place series
    series_by_place, places_meta = {}, []
    for pid in (it.place_ids or []):
        p = places.get(pid)
        if not p:
            continue
        prows = [r for r in rows if r.place_id == pid]
        series_by_place[pid] = {
            "timestamps": [r.timestamp.isoformat() for r in prows],
            "buy":  [_clean(r.buy) for r in prows],
            "sell": [_clean(r.sell) for r in prows],
            "volume": [_clean(r.volume) for r in prows],
        }
        last = prows[-1] if prows else None
        places_meta.append({
            "place_id": pid, "name": p.name, "kind": p.kind, "special": p.special_parser,
            "latest_buy": _clean(last.buy) if last else None,
            "latest_sell": _clean(last.sell) if last else None,
            "latest_volume": _clean(last.volume) if last else None,
            "points": len(prows),
        })

    # choose place for indicators
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
            win = max(2, int(window))
            sma = mid.rolling(win).mean()
            std = mid.rolling(win).std()
            ema = mid.ewm(span=win, adjust=False).mean()
            delta = mid.diff(); up = delta.clip(lower=0); dn = -delta.clip(upper=0)
            rs = up.rolling(14).mean() / dn.rolling(14).mean()
            rsi = 100 - 100 / (1 + rs)
            ema12 = mid.ewm(span=12, adjust=False).mean(); ema26 = mid.ewm(span=26, adjust=False).mean()
            macd = ema12 - ema26; macd_sig = macd.ewm(span=9, adjust=False).mean()
            hi9 = mid.rolling(9).max(); lo9 = mid.rolling(9).min(); tenkan = (hi9 + lo9) / 2
            hi26 = mid.rolling(26).max(); lo26 = mid.rolling(26).min(); kijun = (hi26 + lo26) / 2
            senkou_a = ((tenkan + kijun) / 2).shift(26)
            hi52 = mid.rolling(52).max(); lo52 = mid.rolling(52).min()
            senkou_b = ((hi52 + lo52) / 2).shift(26)

            indicators = {
                "timestamps": s["timestamps"],
                "buy": _ser(buy), "sell": _ser(sell), "mid": _ser(mid),
                "sma": _ser(sma), "ema": _ser(ema),
                "bb_upper": _ser(sma + 2 * std), "bb_lower": _ser(sma - 2 * std),
                "rsi": _ser(rsi), "macd": _ser(macd), "macd_signal": _ser(macd_sig),
                "macd_hist": _ser(macd - macd_sig),
                "tenkan": _ser(tenkan), "kijun": _ser(kijun),
                "senkou_a": _ser(senkou_a), "senkou_b": _ser(senkou_b),
            }
            md = mid.dropna()
            if len(md) >= 5:
                counts, edges = np.histogram(md, bins=min(30, max(8, len(md) // 3)))
                distribution = {"counts": counts.tolist(), "edges": [float(e) for e in edges]}
            lb = _clean(buy.iloc[-1]); ls = _clean(sell.iloc[-1])
            if lb and ls:
                spread = {"buy": lb, "sell": ls, "abs": round(ls - lb, 2),
                          "pct": round((ls - lb) / ls * 100, 2) if ls else None}

    return {
        "item": {"id": it.id, "type_id": it.type_id, "name": it.name},
        "places": places_meta,
        "series_by_place": series_by_place,
        "selected_place_id": sel,
        "window": max(2, int(window)),
        "indicators": indicators,
        "distribution": distribution,
        "spread": spread,
    }
