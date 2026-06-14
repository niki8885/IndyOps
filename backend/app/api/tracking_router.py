"""
Per-user item price tracking — favourite places, tracked items, and a
detail endpoint with technical indicators + cross-place comparison.
"""
import math
import time as _time
from typing import Optional, List

import numpy as np
import pandas as pd
import requests as _requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db, UserDB, TrackedPlace, TrackedItem, TrackPrice
from app.core.database_eve import EveSessionLocal, EveType
from app.core.security import get_current_user
from app.tasks.update_tracking import collect_for_user, _fuzzwork, _gnf

router = APIRouter()

MAX_PLACES = 5
MAX_ITEMS = 100

# ── ESI 30-day region history (cached) ──
_HIST_CACHE: dict = {}
_HIST_TTL = 6 * 3600


def _esi_history(region_id: int, type_id: int) -> Optional[list]:
    key = (region_id, type_id)
    now = _time.time()
    hit = _HIST_CACHE.get(key)
    if hit and now - hit[0] < _HIST_TTL:
        return hit[1]
    try:
        r = _requests.get(
            f"https://esi.evetech.net/latest/markets/{region_id}/history/",
            params={"type_id": type_id, "datasource": "tranquility"},
            headers={"User-Agent": "IndyOps/1.0"}, timeout=25,
        )
        r.raise_for_status()
        data = r.json()[-30:]
    except Exception:
        data = None
    _HIST_CACHE[key] = (now, data)
    return data


def _hist_stats(rows: Optional[list]) -> dict:
    if not rows:
        return {"avg": None, "min": None, "max": None, "vol": None}
    avg = float(np.mean([d["average"] for d in rows]))
    lo = float(min(d["lowest"] for d in rows))
    hi = float(max(d["highest"] for d in rows))
    vol = float(np.mean([d["volume"] for d in rows]))
    return {"avg": round(avg, 2), "min": round(lo, 2), "max": round(hi, 2), "vol": round(vol, 0)}


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


# ── Warehouse allocation / sell-decision ──
class AllocItem(BaseModel):
    type_id: int
    name: str
    quantity: int
    cost: Optional[float] = None     # cost basis per unit (for profit)


class AllocateRequest(BaseModel):
    items: List[AllocItem]
    place_ids: List[int]
    strategy: str = "balanced"        # fast | balanced | maxprofit
    fees_pct: float = 8.0             # broker + tax on sell orders
    delivery_coef: float = 1200.0     # ISK/m³
    delivery_place_ids: List[int] = []
    balance_days: int = 7


def _current_prices(place: TrackedPlace, type_id: int) -> dict:
    """Live buy/sell for a place."""
    if place.special_parser:
        d = _gnf(type_id) or {}
        return {"buy": d.get("buy"), "sell": d.get("sell")}
    e = (_fuzzwork(place.region_id, [type_id]) or {}).get(str(type_id)) or {}
    def f(v):
        try: return float(v)
        except (TypeError, ValueError): return None
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
        vol_map = {tid: vol for tid, vol in eve_db.query(EveType.type_id, EveType.volume)
                   .filter(EveType.type_id.in_([i.type_id for i in body.items] or [-1])).all()}
    finally:
        eve_db.close()

    fees = body.fees_pct / 100.0
    out_items = []
    for it in body.items:
        unit_vol = vol_map.get(it.type_id) or 0
        venues = []
        for pid, p in places.items():
            cur = _current_prices(p, it.type_id)
            hist = _hist_stats(_esi_history(p.region_id, it.type_id)) if p.region_id else {"avg": None, "min": None, "max": None, "vol": None}
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

        allocations = _allocate(venues, it.quantity, body.strategy, body.balance_days)
        total_net = round(sum(a["net_total"] for a in allocations), 2)
        total_profit = round(total_net - (it.cost or 0) * it.quantity, 2) if it.cost else None
        out_items.append({
            "type_id": it.type_id, "name": it.name, "quantity": it.quantity, "cost": it.cost,
            "signal": signal, "venues": venues, "allocations": allocations,
            "total_net": total_net, "total_profit": total_profit,
        })

    return {"strategy": body.strategy, "items": out_items}


def _allocate(venues: list, qty: int, strategy: str, balance_days: int) -> list:
    """Split qty across venues by strategy → [{place, qty, method, unit_net, net_total, est_days}]."""
    def row(v, q, method, unit):
        vol = v["hist"]["vol"] or 0
        days = round(q / vol, 1) if (method == "sell order" and vol) else 0
        return {"place_id": v["place_id"], "place_name": v["place_name"], "qty": q,
                "method": method, "unit_net": unit, "net_total": round((unit or 0) * q, 2), "est_days": days}

    instant = [v for v in venues if v["net_instant"] is not None]
    patient = [v for v in venues if v["net_patient"] is not None]

    if strategy == "fast":
        if not instant:
            return []
        v = max(instant, key=lambda v: v["net_instant"])
        return [row(v, qty, "instant (buy order)", v["net_instant"])]

    if strategy == "maxprofit":
        if not patient:
            return []
        v = max(patient, key=lambda v: v["net_patient"])
        return [row(v, qty, "sell order", v["net_patient"])]

    # balanced: fill best sell-order venues up to capacity (vol × days), remainder instant
    allocs, remaining = [], qty
    for v in sorted(patient, key=lambda v: v["net_patient"], reverse=True):
        if remaining <= 0:
            break
        cap = int((v["hist"]["vol"] or 0) * balance_days) or remaining
        take = min(remaining, cap)
        if take > 0:
            allocs.append(row(v, take, "sell order", v["net_patient"]))
            remaining -= take
    if remaining > 0 and instant:
        v = max(instant, key=lambda v: v["net_instant"])
        allocs.append(row(v, remaining, "instant (buy order)", v["net_instant"]))
        remaining = 0
    return allocs
