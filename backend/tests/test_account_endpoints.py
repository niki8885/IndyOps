"""Account / Tracking endpoints (orders, dashboard, currency, price-check).

Driven the project's no-HTTP way: the async endpoint functions are called directly
with seeded in-memory SQLite sessions; the only network touch (the live region book
in price-check) is monkeypatched.
"""
import asyncio
import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import account_router as ar
from app.core.database import (
    Base, LinkedCharacter, EsiMarketOrder, EsiSkill, EsiIndustryJob, EsiContract,
    BankLedgerEntry,
)
from app.core.database_eve import EveBase, EveType, EveStation, EveSolarSystem, EveRegion
from app.services import skills as skills_svc
from app.services import ratelimit

CID = 99
USER = SimpleNamespace(id=1)
SCOPE = "esi-markets.read_character_orders.v1"


def run(coro):
    return asyncio.run(coro)


def _mem_db(base):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


@pytest.fixture
def app_db():
    session, engine = _mem_db(Base)
    yield session
    session.close(); engine.dispose()


@pytest.fixture
def eve_db():
    session, engine = _mem_db(EveBase)
    yield session
    session.close(); engine.dispose()


def _seed_sde(eve_db):
    eve_db.add_all([
        EveType(type_id=34, type_name="Tritanium", group_id=18, volume=0.01, published=True),
        EveStation(station_id=60003760, station_name="Jita IV - Moon 4 - Caldari Navy Assembly Plant",
                   solar_system_id=30000142, region_id=10000002),
        EveSolarSystem(solar_system_id=30000142, solar_system_name="Jita", region_id=10000002),
        EveRegion(region_id=10000002, region_name="The Forge"),
    ])
    eve_db.commit()


def _seed_char(app_db, scopes=SCOPE):
    app_db.add(LinkedCharacter(id=1, user_id=1, character_id=CID, character_name="Trader",
                               scopes=scopes, is_active=True, status="active", wallet_balance=1_000_000.0))
    app_db.commit()


def _order(**kw):
    base = dict(character_id=CID, type_id=34, region_id=10000002, location_id=60003760,
                volume_total=100, volume_remain=50, min_volume=1, range="region", duration=90,
                issued=datetime.datetime(2026, 6, 20, 12, 0, 0))
    base.update(kw)
    return EsiMarketOrder(**base)


# ── /account/orders ──────────────────────────────────────────────────────────

def test_orders_splits_sides_and_enriches_names(app_db, eve_db):
    _seed_sde(eve_db)
    _seed_char(app_db)
    app_db.add_all([
        _order(order_id=1, is_buy_order=False, price=5.5),
        _order(order_id=2, is_buy_order=True, price=4.0, escrow=200.0, volume_remain=3),
    ])
    app_db.add(EsiSkill(character_id=CID, skill_id=skills_svc.SKILL_TRADE, trained_level=5))  # +20 slots
    app_db.commit()

    out = run(ar.get_orders(scope="all", current_user=USER, db=app_db, eve_db=eve_db))
    assert len(out["selling"]) == 1 and len(out["buying"]) == 1
    sell = out["selling"][0]
    assert sell["type_name"] == "Tritanium"
    assert sell["station"].startswith("Jita IV")
    assert sell["system"] == "Jita" and sell["region"] == "The Forge"
    assert sell["owner"] == "Trader"
    # summary: order-slot capacity = 5 base + 20 (Trade V); 2 orders used
    assert out["summary"]["order_slots"] == {"used": 2, "max": 25}
    assert out["summary"]["sell_isk"] == pytest.approx(5.5 * 50)
    assert out["summary"]["buy_escrow"] == pytest.approx(200.0)
    assert out["needs_scope"] == []


def test_orders_flags_missing_scope(app_db, eve_db):
    _seed_sde(eve_db)
    _seed_char(app_db, scopes="publicData")   # no market-orders scope
    out = run(ar.get_orders(scope="all", current_user=USER, db=app_db, eve_db=eve_db))
    assert out["needs_scope"] == ["Trader"]


# ── /account/orders/price-check ──────────────────────────────────────────────

def test_price_check_marks_outbid(app_db, eve_db, monkeypatch):
    ratelimit._last.clear()   # in-process cooldown is global; isolate this test
    _seed_char(app_db)
    app_db.add(_order(order_id=1, is_buy_order=False, price=10.0))
    app_db.commit()
    # a competitor sells cheaper → our order is outbid
    monkeypatch.setattr(ar.market, "esi_region_orders",
                        lambda region, type_id: [{"order_id": 555, "is_buy_order": False, "price": 9.0}])
    out = run(ar.price_check(body=ar.ScopeBody(scope="all"), current_user=USER, db=app_db))
    assert out["checked"] == 1
    assert out["prices"]["1"]["status"] == "outbid"
    assert out["prices"]["1"]["best_competitor"] == 9.0


def test_price_check_is_rate_limited(app_db, monkeypatch):
    ratelimit._last.clear()   # in-process cooldown is global; isolate this test
    _seed_char(app_db)
    monkeypatch.setattr(ar.market, "esi_region_orders", lambda r, t: [])
    first = run(ar.price_check(body=ar.ScopeBody(scope="all"), current_user=USER, db=app_db))
    assert "prices" in first
    again = run(ar.price_check(body=ar.ScopeBody(scope="all"), current_user=USER, db=app_db))
    assert getattr(again, "status_code", None) == 429    # JSONResponse, not a dict


# ── /account/dashboard + /account/currency ───────────────────────────────────

def test_dashboard_aggregates_and_currency(app_db):
    _seed_char(app_db)
    app_db.add_all([
        _order(order_id=1, is_buy_order=False, price=5.0, volume_remain=10),     # sell 50
        _order(order_id=2, is_buy_order=True, price=4.0, volume_remain=10, escrow=30.0),  # buy 40
        EsiIndustryJob(character_id=CID, job_id=1, activity_id=1, status="active"),       # mfg slot used
        EsiContract(character_id=CID, contract_id=1, status="outstanding"),
        BankLedgerEntry(user_id=1, character_id=CID, ref_id=777, amount_penny=100011, amount_isk=1000.11),
    ])
    app_db.commit()

    d = run(ar.dashboard(current_user=USER, db=app_db))
    assert len(d["characters"]) == 1
    c = d["characters"][0]
    assert c["sell_isk"] == pytest.approx(50.0) and c["buy_isk"] == pytest.approx(40.0)
    assert c["escrow"] == pytest.approx(30.0)
    assert c["slots"]["manufacturing"] == {"used": 1, "max": 1}
    assert c["jobs"]["manufacturing"] == 1
    assert c["contracts"] == 1
    assert d["totals"]["wallet"] == pytest.approx(1_000_000.0)
    # 1,000.11 ISK donated → 1000 Aureus + 11 Penny
    assert d["currency"] == {"total_penny": 100011, "aureus": 1000, "penny": 11}

    cur = run(ar.get_currency(current_user=USER, db=app_db))
    assert cur["balance"]["aureus"] == 1000 and cur["balance"]["penny"] == 11
    assert len(cur["deposits"]) == 1 and cur["deposits"][0]["amount_isk"] == pytest.approx(1000.11)
