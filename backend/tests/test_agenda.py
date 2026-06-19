"""
Agenda page — alert evaluation (pure), alert CRUD + ticker + notifications
endpoints, and the worker evaluator. Driven against in-memory SQLite the
project's no-HTTP way: async endpoint functions called directly with a seeded
session; the worker's ``evaluate_alerts(db)`` is fed the same session.
"""
import asyncio
import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import agenda_router as ag
from app.services import alerts as alert_svc
from app.tasks.evaluate_alerts import evaluate_alerts
from app.core.database import (
    Base, MarketIndexSnapshot, TrackedItem, TrackPrice, AgendaNotification, PriceAlert,
)

USER = SimpleNamespace(id=1)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close(); engine.dispose()


def _snap(db, key, price, hours_ago=0, volume=100.0):
    db.add(MarketIndexSnapshot(
        index_key=key, price_index=price, volume_index=volume,
        timestamp=datetime.datetime(2026, 6, 19, 12, 0) - datetime.timedelta(hours=hours_ago)))
    db.commit()


# ── pure service ──────────────────────────────────────────────────────────────

def test_is_triggered_rules():
    assert alert_svc.is_triggered("above", 105, None, 100) is True
    assert alert_svc.is_triggered("above", 95, None, 100) is False
    assert alert_svc.is_triggered("below", 95, None, 100) is True
    assert alert_svc.is_triggered("pct_up", 110, 100, 5) is True       # +10% ≥ 5%
    assert alert_svc.is_triggered("pct_up", 102, 100, 5) is False      # +2% < 5%
    assert alert_svc.is_triggered("pct_down", 90, 100, 5) is True      # -10% ≤ -5%
    assert alert_svc.is_triggered("pct_up", 110, None, 5) is False     # no baseline
    assert alert_svc.is_triggered("above", None, None, 100) is False   # no data


def test_severity():
    assert alert_svc.severity("above") == "up"
    assert alert_svc.severity("pct_down") == "down"


# ── alert CRUD + validation ─────────────────────────────────────────────────

def test_create_index_alert_and_list(db):
    out = run(ag.create_alert(body=ag.AlertCreate(
        target_kind="index", index_key="plex", condition="above", threshold=5_000_000),
        current_user=USER, db=db))
    assert out["target_kind"] == "index" and out["label"] == "PLEX" and out["active"] is True

    rows = run(ag.list_alerts(current_user=USER, db=db))
    assert len(rows) == 1 and rows[0]["id"] == out["id"]


def test_create_alert_rejects_bad_input(db):
    with pytest.raises(Exception):
        run(ag.create_alert(body=ag.AlertCreate(
            target_kind="index", index_key="nope", condition="above", threshold=1),
            current_user=USER, db=db))
    with pytest.raises(Exception):
        run(ag.create_alert(body=ag.AlertCreate(
            target_kind="item", item_id=999, condition="above", threshold=1),
            current_user=USER, db=db))


def test_toggle_and_delete_alert(db):
    a = run(ag.create_alert(body=ag.AlertCreate(
        target_kind="index", index_key="mineral", condition="below", threshold=1),
        current_user=USER, db=db))
    upd = run(ag.update_alert(alert_id=a["id"], body=ag.AlertUpdate(active=False),
                              current_user=USER, db=db))
    assert upd["active"] is False
    run(ag.delete_alert(alert_id=a["id"], current_user=USER, db=db))
    assert run(ag.list_alerts(current_user=USER, db=db)) == []


# ── ticker ────────────────────────────────────────────────────────────────────

def test_ticker_includes_indices_and_items(db):
    _snap(db, "plex", 4_900_000, hours_ago=1)
    _snap(db, "plex", 5_000_000, hours_ago=0)
    db.add(TrackedItem(id=7, user_id=1, type_id=34, name="Tritanium", place_ids=[1]))
    db.add(TrackPrice(user_id=1, type_id=34, place_id=1, sell=5.5, volume=999,
                      timestamp=datetime.datetime(2026, 6, 19, 12, 0)))
    db.commit()

    t = run(ag.ticker(current_user=USER, db=db))
    plex = next(e for e in t["entries"] if e["key"] == "plex")
    assert plex["kind"] == "index" and plex["price"] == pytest.approx(5_000_000)
    assert plex["change_pct"] == pytest.approx((5_000_000 - 4_900_000) / 4_900_000 * 100)
    trit = next(e for e in t["entries"] if e["kind"] == "item")
    assert trit["label"] == "Tritanium" and trit["price"] == pytest.approx(5.5)


# ── worker evaluation + notifications ───────────────────────────────────────

def test_evaluator_fires_one_shot_and_disarms(db):
    _snap(db, "plex", 5_200_000)
    run(ag.create_alert(body=ag.AlertCreate(
        target_kind="index", index_key="plex", condition="above", threshold=5_000_000),
        current_user=USER, db=db))

    res = evaluate_alerts(db)
    assert res == {"checked": 1, "fired": 1}

    # one-shot disarmed → second pass does nothing
    assert evaluate_alerts(db)["fired"] == 0
    a = db.query(PriceAlert).first()
    assert a.active is False and a.last_triggered_at is not None

    feed = run(ag.list_notifications(limit=50, unread_only=False, current_user=USER, db=db))
    assert feed["unread"] == 1 and feed["notifications"][0]["severity"] == "up"
    assert "PLEX" in feed["notifications"][0]["title"]


def test_evaluator_pct_move_on_index(db):
    _snap(db, "mineral", 100.0, hours_ago=30)   # baseline > window ago
    _snap(db, "mineral", 130.0, hours_ago=0)    # +30%
    run(ag.create_alert(body=ag.AlertCreate(
        target_kind="index", index_key="mineral", condition="pct_up",
        threshold=10, window_hours=24, repeat=True),
        current_user=USER, db=db))
    assert evaluate_alerts(db)["fired"] == 1
    # repeating alert stays active but is on cooldown
    a = db.query(PriceAlert).first()
    assert a.active is True
    assert evaluate_alerts(db)["fired"] == 0


def test_notifications_read_flow(db):
    db.add(AgendaNotification(user_id=1, severity="up", title="x", body="y"))
    db.commit()
    run(ag.read_all(current_user=USER, db=db))
    feed = run(ag.list_notifications(limit=50, unread_only=False, current_user=USER, db=db))
    assert feed["unread"] == 0 and feed["notifications"][0]["read"] is True
