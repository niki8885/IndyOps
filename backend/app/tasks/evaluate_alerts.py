"""
Evaluate user price/volume alerts and deliver Agenda notifications.

Runs on the worker every few minutes. For each active ``PriceAlert`` it reads the
current (and window-ago, for % conditions) value of the target metric — a
commodity index snapshot or a tracked-item price row — and, when the condition
in ``app.services.alerts`` trips, writes an ``AgendaNotification``. One-shot
alerts disarm (``active=False``); repeating alerts honour a cooldown so the feed
isn't re-spammed every run.
"""
from __future__ import annotations

import datetime
import logging

from app.core.database import (
    SessionLocal, PriceAlert, AgendaNotification, MarketIndexSnapshot,
    TrackPrice, TrackedItem,
)
from app.core.indices_data import INDEX_META
from app.core.timeutil import utcnow
from app.services import alerts as alert_svc

logger = logging.getLogger(__name__)

REPEAT_COOLDOWN_HOURS = 6


def _metric_of(row, metric: str):
    if metric == "volume":
        return row.volume_index if isinstance(row, MarketIndexSnapshot) else row.volume
    if isinstance(row, MarketIndexSnapshot):
        return row.price_index
    return row.sell if row.sell is not None else row.buy


def _index_values(db, index_key, metric, window_hours):
    latest = (db.query(MarketIndexSnapshot)
              .filter(MarketIndexSnapshot.index_key == index_key)
              .order_by(MarketIndexSnapshot.timestamp.desc()).first())
    if latest is None:
        return None, None
    cutoff = latest.timestamp - datetime.timedelta(hours=window_hours)
    past = (db.query(MarketIndexSnapshot)
            .filter(MarketIndexSnapshot.index_key == index_key,
                    MarketIndexSnapshot.timestamp <= cutoff)
            .order_by(MarketIndexSnapshot.timestamp.desc()).first())
    return _metric_of(latest, metric), (_metric_of(past, metric) if past else None)


def _item_values(db, user_id, type_id, place_id, metric, window_hours):
    q = (db.query(TrackPrice)
         .filter(TrackPrice.user_id == user_id, TrackPrice.type_id == type_id))
    if place_id is not None:
        q = q.filter(TrackPrice.place_id == place_id)
    latest = q.order_by(TrackPrice.timestamp.desc()).first()
    if latest is None:
        return None, None
    cutoff = latest.timestamp - datetime.timedelta(hours=window_hours)
    past = (db.query(TrackPrice)
            .filter(TrackPrice.user_id == user_id, TrackPrice.type_id == type_id,
                    TrackPrice.place_id == latest.place_id, TrackPrice.timestamp <= cutoff)
            .order_by(TrackPrice.timestamp.desc()).first())
    return _metric_of(latest, metric), (_metric_of(past, metric) if past else None)


def _fmt(v) -> str:
    return "—" if v is None else f"{v:,.2f}"


def _condition_phrase(alert) -> str:
    m = alert.metric
    if alert.condition == "above":
        return f"{m} crossed above {_fmt(alert.threshold)}"
    if alert.condition == "below":
        return f"{m} dropped below {_fmt(alert.threshold)}"
    if alert.condition == "pct_up":
        return f"{m} up ≥ {_fmt(alert.threshold)}% ({alert.window_hours}h)"
    if alert.condition == "pct_down":
        return f"{m} down ≥ {_fmt(alert.threshold)}% ({alert.window_hours}h)"
    return "triggered"


def _body(alert, current, past) -> str:
    parts = [f"Now {_fmt(current)}"]
    chg = alert_svc.pct_change(past, current)
    if chg is not None:
        parts.append(f"{chg:+.1f}% vs {alert.window_hours}h ago")
    if alert.note:
        parts.append(alert.note)
    return " · ".join(parts)


def _evaluate_one(db, alert, now) -> bool:
    if alert.target_kind == "index":
        if not alert.index_key:
            return False
        current, past = _index_values(db, alert.index_key, alert.metric, alert.window_hours)
        label = INDEX_META.get(alert.index_key, {}).get("label", alert.index_key)
    else:
        item = (db.query(TrackedItem)
                .filter(TrackedItem.id == alert.item_id, TrackedItem.user_id == alert.user_id)
                .first())
        if item is None:
            return False
        place_id = alert.place_id
        if place_id is None and item.place_ids:
            place_id = item.place_ids[0]
        current, past = _item_values(db, alert.user_id, item.type_id, place_id,
                                     alert.metric, alert.window_hours)
        label = item.name

    alert.last_value = current
    if not alert_svc.is_triggered(alert.condition, current, past, alert.threshold):
        return False

    # don't re-spam a repeating alert that just fired
    if (alert.repeat and alert.last_triggered_at is not None
            and now - alert.last_triggered_at < datetime.timedelta(hours=REPEAT_COOLDOWN_HOURS)):
        return False

    db.add(AgendaNotification(
        user_id=alert.user_id, alert_id=alert.id,
        severity=alert_svc.severity(alert.condition),
        title=f"{label}: {_condition_phrase(alert)}",
        body=_body(alert, current, past),
    ))
    alert.last_triggered_at = now
    if not alert.repeat:
        alert.active = False
    return True


def evaluate_alerts(db) -> dict:
    """Evaluate every active alert against the latest data, delivering notifications.
    Takes a session so it's testable; ``run_alert_evaluation`` wraps it for the worker."""
    now = utcnow()
    active = db.query(PriceAlert).filter(PriceAlert.active.is_(True)).all()
    fired = 0
    for alert in active:
        try:
            if _evaluate_one(db, alert, now):
                fired += 1
        except Exception:
            logger.exception("alert %s: evaluation failed", alert.id)
    db.commit()
    return {"checked": len(active), "fired": fired}


def run_alert_evaluation() -> dict:
    db = SessionLocal()
    try:
        return evaluate_alerts(db)
    finally:
        db.close()
