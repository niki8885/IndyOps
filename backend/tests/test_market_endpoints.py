"""
Market Browser endpoints (app/api/market_router.py): type header, live orders,
order book, history analytics and the correlation matrix. Tested the project's
no-HTTP way — the async route functions are called directly with seeded in-memory
SQLite sessions, and every ESI/market adapter call is monkeypatched so no network
is touched. Adapter fakes mirror the real shapes from app/adapters/market.py
(``esi_region_orders`` order dicts, ``esi_region_history_full`` daily-history
dicts) and the seeded SDE supplies the EveType / region / station rows the routes
resolve against.
"""
import asyncio
import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.market_router as mr
from app.core.database import Base
from app.core.database_eve import (
    EveBase, EveType, EveGroup, EveRegion, EveSolarSystem, EveStation, EveMarketGroup,
)

USER = SimpleNamespace(id=1)

REGION = 10000002          # The Forge
TYPE_ID = 34               # Tritanium
GROUP_ID = 18              # Minerals
MARKET_GROUP_ID = 1857


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


# ── SDE seed ─────────────────────────────────────────────────────────────────

def _seed_sde(eve_db):
    """One type (Tritanium) + a peer in the same group, region, system, station,
    market-group breadcrumb, and the correlation reference types."""
    eve_db.add_all([
        EveGroup(group_id=GROUP_ID, category_id=4, group_name="Minerals"),
        EveMarketGroup(market_group_id=MARKET_GROUP_ID, parent_group_id=None,
                       market_group_name="Minerals"),
        EveType(type_id=TYPE_ID, type_name="Tritanium", group_id=GROUP_ID,
                volume=0.01, published=True, market_group_id=MARKET_GROUP_ID),
        # a published, market-listed peer in the same group → correlation peer
        EveType(type_id=35, type_name="Pyerite", group_id=GROUP_ID,
                volume=0.01, published=True, market_group_id=MARKET_GROUP_ID),
        EveRegion(region_id=REGION, region_name="The Forge"),
        EveSolarSystem(solar_system_id=30000142, region_id=REGION,
                       solar_system_name="Jita", security=0.9),
        EveStation(station_id=60003760, station_name="Jita IV - Moon 4 - CNAP",
                   solar_system_id=30000142, region_id=REGION),
    ])
    # remaining reference types used by /correlation (34 & 35 already added)
    for tid, name in [(1230, "Veldspar"), (16273, "Liquid Ozone"),
                      (16634, "Helium Isotopes"), (44992, "PLEX")]:
        eve_db.add(EveType(type_id=tid, type_name=name, group_id=999,
                           volume=1.0, published=True, market_group_id=MARKET_GROUP_ID))
    eve_db.commit()


# ── adapter fakes (mirror app/adapters/market.py shapes) ──────────────────────

_ISSUED = "2026-06-01T12:00:00Z"


def _fake_orders():
    """A couple of sell + buy orders at a known NPC station, ESI order shape."""
    return [
        {"order_id": 1, "price": 5.0, "volume_remain": 1000, "volume_total": 1000,
         "is_buy_order": False, "location_id": 60003760, "system_id": 30000142,
         "duration": 90, "issued": _ISSUED, "range": "region", "min_volume": 1},
        {"order_id": 2, "price": 6.0, "volume_remain": 500, "volume_total": 500,
         "is_buy_order": False, "location_id": 60003760, "system_id": 30000142,
         "duration": 90, "issued": _ISSUED, "range": "region", "min_volume": 1},
        {"order_id": 3, "price": 4.0, "volume_remain": 800, "volume_total": 800,
         "is_buy_order": True, "location_id": 60003760, "system_id": 30000142,
         "duration": 30, "issued": _ISSUED, "range": "region", "min_volume": 1},
    ]


def _fake_history(base=5.0, n=40):
    """``n`` days of ESI daily-history rows ending today, gentle wave so returns
    are non-trivial (history analytics + correlation need real variation)."""
    start = datetime.date(2026, 5, 1)
    rows = []
    for i in range(n):
        avg = base + (i % 5) * 0.1  # small repeating wiggle
        rows.append({
            "date": (start + datetime.timedelta(days=i)).isoformat(),
            "average": avg,
            "highest": avg + 0.2,
            "lowest": avg - 0.2,
            "volume": 100000 + i * 100,
            "order_count": 50 + i,
        })
    return rows


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(mr.market, "esi_region_orders", lambda region, type_id: _fake_orders())
    monkeypatch.setattr(mr.market, "esi_region_history_full", lambda region, type_id: _fake_history())


# ── /type/{type_id} ───────────────────────────────────────────────────────────

def test_type_header_success(eve_db):
    _seed_sde(eve_db)
    out = run(mr.type_header(type_id=TYPE_ID, current_user=USER, eve_db=eve_db))
    assert out["type_id"] == TYPE_ID
    assert out["type_name"] == "Tritanium"
    assert out["group_name"] == "Minerals"
    assert str(TYPE_ID) in out["icon_url"]
    assert out["breadcrumb"] == [{"id": MARKET_GROUP_ID, "name": "Minerals"}]


def test_type_header_unknown_type_404(eve_db):
    _seed_sde(eve_db)
    with pytest.raises(mr.HTTPException):
        run(mr.type_header(type_id=999999, current_user=USER, eve_db=eve_db))


# ── /orders ────────────────────────────────────────────────────────────────────

def test_orders_success(eve_db):
    _seed_sde(eve_db)
    out = run(mr.orders(region_id=REGION, type_id=TYPE_ID, current_user=USER, eve_db=eve_db))
    assert out["region_id"] == REGION
    assert out["type_id"] == TYPE_ID
    assert out["count"] == 3
    # 2 sell orders, cheapest first
    assert len(out["sellers"]) == 2
    assert out["sellers"][0]["price"] == 5.0
    assert out["sellers"][0]["location"] == "Jita IV - Moon 4 - CNAP"
    assert out["sellers"][0]["region"] == "The Forge"
    # 1 buy order
    assert len(out["buyers"]) == 1
    assert out["buyers"][0]["price"] == 4.0
    assert out["summary"]["best_sell"] == 5.0
    assert out["summary"]["best_buy"] == 4.0
    assert out["summary"]["spread"] == 1.0


# ── /orderbook ──────────────────────────────────────────────────────────────────

def test_orderbook_success(eve_db):
    _seed_sde(eve_db)
    # orderbook route takes no eve_db
    out = run(mr.orderbook(region_id=REGION, type_id=TYPE_ID, depth=60, current_user=USER))
    assert out["region_id"] == REGION
    assert out["type_id"] == TYPE_ID
    # two distinct ask price-levels (5.0, 6.0), one bid level (4.0)
    assert [a["price"] for a in out["asks"]] == [5.0, 6.0]
    assert [b["price"] for b in out["bids"]] == [4.0]
    assert out["best_ask"] == 5.0
    assert out["best_bid"] == 4.0
    assert out["spread"] == 1.0


# ── /history ─────────────────────────────────────────────────────────────────────

def test_history_success(app_db, eve_db):
    _seed_sde(eve_db)
    out = run(mr.history(region_id=REGION, type_id=TYPE_ID, window=10, refresh=False,
                         current_user=USER, db=app_db, eve_db=eve_db))
    assert out["type_id"] == TYPE_ID
    assert out["label"] == "Tritanium"
    assert out["region_id"] == REGION
    assert out["region_name"] == "The Forge"
    assert out["stats"]["points"] == 40
    assert "price" in out["series"]
    # second call should be served from the read-through cache (set on first call)
    out2 = run(mr.history(region_id=REGION, type_id=TYPE_ID, window=10, refresh=False,
                          current_user=USER, db=app_db, eve_db=eve_db))
    assert out2["type_id"] == TYPE_ID and out2["label"] == "Tritanium"


def test_history_empty_when_no_rows(app_db, eve_db, monkeypatch):
    _seed_sde(eve_db)
    monkeypatch.setattr(mr.market, "esi_region_history_full", lambda region, type_id: None)
    out = run(mr.history(region_id=REGION, type_id=TYPE_ID, window=10, refresh=True,
                         current_user=USER, db=app_db, eve_db=eve_db))
    assert out["empty"] is True
    assert out["label"] == "Tritanium"
    assert out["region_id"] == REGION


# ── /correlation ───────────────────────────────────────────────────────────────

def test_correlation_success(eve_db):
    _seed_sde(eve_db)
    out = run(mr.correlation(region_id=REGION, type_id=TYPE_ID, current_user=USER, eve_db=eve_db))
    assert out["region_id"] == REGION
    assert out["type_id"] == TYPE_ID
    assert out["target"] == "Tritanium"
    # target + peer + reference types all resolved to labels
    assert "Tritanium" in out["labels"]
    assert isinstance(out["matrix"], list)
    assert isinstance(out["to_target"], list)


def test_correlation_unknown_type_404(eve_db):
    _seed_sde(eve_db)
    with pytest.raises(mr.HTTPException):
        run(mr.correlation(region_id=REGION, type_id=999999, current_user=USER, eve_db=eve_db))
