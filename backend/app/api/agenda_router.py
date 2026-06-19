"""
Agenda page — the app's home tab.

Powers three things:
  * a ticker of commodity-index levels + the user's tracked-item prices,
  * a notifications feed (delivered by the alert-evaluation worker), and
  * user-defined financial alerts (price above/below, or a % move in price/volume)
    on indices and tracked items.

Alerts are *evaluated* off-request by ``app.tasks.evaluate_alerts`` on the worker;
this router only does CRUD + read models. See [[indyops-service-layering]].
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.responses import ERR_400, ERR_404
from app.core.database import (
    get_db, UserDB, PriceAlert, AgendaNotification, MarketIndexSnapshot,
    TrackPrice, TrackedItem, TrackedPlace,
)
from app.core.indices_data import INDEX_META, INDEX_ORDER
from app.core.security import get_current_user
from app.core.timeutil import utcnow
from app.services import alerts as alert_svc
from app.services._numeric import clean

router = APIRouter()


# ── ticker ───────────────────────────────────────────────────────────────────

def _index_entries(db: Session) -> list:
    out = []
    for key in INDEX_ORDER:
        rows = (db.query(MarketIndexSnapshot)
                .filter(MarketIndexSnapshot.index_key == key)
                .order_by(MarketIndexSnapshot.timestamp.desc()).limit(2).all())
        if not rows:
            continue
        last, prev = rows[0], (rows[1] if len(rows) > 1 else None)
        change = alert_svc.pct_change(prev.price_index if prev else None, last.price_index)
        out.append({
            "kind": "index", "key": key, "label": INDEX_META[key]["label"],
            "price": clean(last.price_index), "volume": clean(last.volume_index),
            "change_pct": clean(change),
        })
    return out


def _item_entries(db: Session, user_id: int) -> list:
    out = []
    items = db.query(TrackedItem).filter(TrackedItem.user_id == user_id).order_by(TrackedItem.name).all()
    for it in items:
        last = (db.query(TrackPrice)
                .filter(TrackPrice.user_id == user_id, TrackPrice.type_id == it.type_id)
                .order_by(TrackPrice.timestamp.desc()).first())
        if last is None:
            continue
        prev = (db.query(TrackPrice)
                .filter(TrackPrice.user_id == user_id, TrackPrice.type_id == it.type_id,
                        TrackPrice.place_id == last.place_id, TrackPrice.id != last.id)
                .order_by(TrackPrice.timestamp.desc()).first())
        price = last.sell if last.sell is not None else last.buy
        prev_price = (prev.sell if prev.sell is not None else prev.buy) if prev else None
        out.append({
            "kind": "item", "key": it.id, "label": it.name,
            "price": clean(price), "volume": clean(last.volume),
            "change_pct": clean(alert_svc.pct_change(prev_price, price)),
        })
    return out


@router.get("/ticker", summary="Index levels + tracked-item prices for the Agenda ticker")
async def ticker(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"entries": _index_entries(db) + _item_entries(db, current_user.id)}


# ── alerts ─────────────────────────────────────────────────────────────────

class AlertCreate(BaseModel):
    target_kind: str                       # 'index' | 'item'
    index_key: Optional[str] = None
    item_id: Optional[int] = None
    place_id: Optional[int] = None
    metric: str = "price"                  # 'price' | 'volume'
    condition: str                         # above | below | pct_up | pct_down
    threshold: float
    window_hours: int = 24
    repeat: bool = False
    note: Optional[str] = None


class AlertUpdate(BaseModel):
    active: Optional[bool] = None
    threshold: Optional[float] = None
    note: Optional[str] = None


def _alert_label(a: PriceAlert, item_names: dict) -> str:
    if a.target_kind == "index":
        return INDEX_META.get(a.index_key, {}).get("label", a.index_key or "?")
    return item_names.get(a.item_id, f"item #{a.item_id}")


def _alert_out(a: PriceAlert, item_names: dict) -> dict:
    return {
        "id": a.id, "target_kind": a.target_kind, "index_key": a.index_key,
        "item_id": a.item_id, "place_id": a.place_id, "metric": a.metric,
        "condition": a.condition, "threshold": a.threshold, "window_hours": a.window_hours,
        "active": a.active, "repeat": a.repeat, "note": a.note,
        "label": _alert_label(a, item_names), "last_value": clean(a.last_value),
        "last_triggered_at": a.last_triggered_at.isoformat() if a.last_triggered_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _item_name_map(db: Session, user_id: int) -> dict:
    return {it.id: it.name for it in
            db.query(TrackedItem).filter(TrackedItem.user_id == user_id).all()}


@router.get("/alerts", summary="List the user's alerts")
async def list_alerts(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (db.query(PriceAlert).filter(PriceAlert.user_id == current_user.id)
            .order_by(PriceAlert.created_at.desc()).all())
    names = _item_name_map(db, current_user.id)
    return [_alert_out(a, names) for a in rows]


@router.post("/alerts", status_code=201, summary="Create an alert", responses={**ERR_400})
async def create_alert(
    body: AlertCreate,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.target_kind not in ("index", "item"):
        raise HTTPException(400, "target_kind must be index | item")
    if body.metric not in alert_svc.METRICS:
        raise HTTPException(400, "metric must be price | volume")
    if body.condition not in alert_svc.CONDITIONS:
        raise HTTPException(400, "bad condition")

    if body.target_kind == "index":
        if body.index_key not in INDEX_META:
            raise HTTPException(400, "unknown index")
        item_id = place_id = None
    else:
        item = (db.query(TrackedItem)
                .filter(TrackedItem.id == body.item_id, TrackedItem.user_id == current_user.id)
                .first())
        if not item:
            raise HTTPException(400, "unknown tracked item")
        item_id = item.id
        place_id = body.place_id
        if place_id is not None:
            place = (db.query(TrackedPlace)
                     .filter(TrackedPlace.id == place_id, TrackedPlace.user_id == current_user.id)
                     .first())
            if not place:
                raise HTTPException(400, "unknown place")

    a = PriceAlert(
        user_id=current_user.id, target_kind=body.target_kind,
        index_key=body.index_key if body.target_kind == "index" else None,
        item_id=item_id, place_id=place_id, metric=body.metric,
        condition=body.condition, threshold=body.threshold,
        window_hours=max(1, min(720, body.window_hours)),
        repeat=body.repeat, note=(body.note or None), active=True,
    )
    db.add(a); db.commit(); db.refresh(a)
    return _alert_out(a, _item_name_map(db, current_user.id))


@router.patch("/alerts/{alert_id}", summary="Toggle / edit an alert", responses={**ERR_404})
async def update_alert(
    alert_id: int,
    body: AlertUpdate,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    a = (db.query(PriceAlert)
         .filter(PriceAlert.id == alert_id, PriceAlert.user_id == current_user.id).first())
    if not a:
        raise HTTPException(404, "Alert not found")
    if body.active is not None:
        a.active = body.active
    if body.threshold is not None:
        a.threshold = body.threshold
    if body.note is not None:
        a.note = body.note or None
    db.commit(); db.refresh(a)
    return _alert_out(a, _item_name_map(db, current_user.id))


@router.delete("/alerts/{alert_id}", status_code=204, summary="Delete an alert", responses={**ERR_404})
async def delete_alert(
    alert_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    a = (db.query(PriceAlert)
         .filter(PriceAlert.id == alert_id, PriceAlert.user_id == current_user.id).first())
    if not a:
        raise HTTPException(404, "Alert not found")
    db.delete(a); db.commit()
    return None


# ── notifications ──────────────────────────────────────────────────────────

def _notif_out(n: AgendaNotification) -> dict:
    return {
        "id": n.id, "alert_id": n.alert_id, "severity": n.severity,
        "title": n.title, "body": n.body,
        "read": n.read_at is not None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("/notifications", summary="Notifications feed (newest first)")
async def list_notifications(
    limit: int = Query(50, ge=1, le=200),
    unread_only: bool = False,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(AgendaNotification).filter(AgendaNotification.user_id == current_user.id)
    if unread_only:
        q = q.filter(AgendaNotification.read_at.is_(None))
    rows = q.order_by(AgendaNotification.created_at.desc(), AgendaNotification.id.desc()).limit(limit).all()
    unread = (db.query(AgendaNotification)
              .filter(AgendaNotification.user_id == current_user.id,
                      AgendaNotification.read_at.is_(None)).count())
    return {"notifications": [_notif_out(n) for n in rows], "unread": unread}


@router.post("/notifications/read-all", summary="Mark all notifications read")
async def read_all(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = utcnow()
    updated = (db.query(AgendaNotification)
               .filter(AgendaNotification.user_id == current_user.id,
                       AgendaNotification.read_at.is_(None))
               .update({AgendaNotification.read_at: now}, synchronize_session=False))
    db.commit()
    return {"read": updated}


@router.post("/notifications/{notif_id}/read", summary="Mark one notification read", responses={**ERR_404})
async def read_one(
    notif_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    n = (db.query(AgendaNotification)
         .filter(AgendaNotification.id == notif_id, AgendaNotification.user_id == current_user.id).first())
    if not n:
        raise HTTPException(404, "Notification not found")
    if n.read_at is None:
        n.read_at = utcnow()
        db.commit()
    return _notif_out(n)


@router.delete("/notifications/{notif_id}", status_code=204, summary="Dismiss a notification", responses={**ERR_404})
async def dismiss(
    notif_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    n = (db.query(AgendaNotification)
         .filter(AgendaNotification.id == notif_id, AgendaNotification.user_id == current_user.id).first())
    if not n:
        raise HTTPException(404, "Notification not found")
    db.delete(n); db.commit()
    return None
