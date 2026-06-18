"""
Price-tracking endpoints (Market Browser favourites): tracked places + items,
the hourly price-history snapshots, the item-detail/indicator read path, a
manual refresh, and the warehouse sell-allocation decision. Exercised the
project's no-HTTP way — the async endpoint functions are called directly with
seeded in-memory SQLite sessions; every market/ESI fetch and the SDE volume
lookup are monkeypatched so no network is touched.
"""
import asyncio
import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import tracking_router as tr
from app.core.database import (
    Base, UserDB, TrackedPlace, TrackedItem, TrackPrice,
)
from app.core.database_eve import EveBase, EveType

USER = SimpleNamespace(id=1)
SEED_HASH = "x"  # placeholder password hash for seeded test users (not a real credential)


def run(coro):
    return asyncio.run(coro)


def _mem_db(base):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


@pytest.fixture
def db():
    session, engine = _mem_db(Base)
    session.add(UserDB(id=1, username="u", email="u@example.com", hashed_password=SEED_HASH))
    session.commit()
    yield session
    session.close(); engine.dispose()


@pytest.fixture
def eve_db():
    session, engine = _mem_db(EveBase)
    yield session
    session.close(); engine.dispose()


# ── seed helpers ──────────────────────────────────────────────────────────────

def _place(db, name="Jita", kind="region", region_id=10000002, system=30000142,
           special=False, user_id=1):
    p = TrackedPlace(user_id=user_id, kind=kind, name=name, region_id=region_id,
                     solar_system_id=system, special_parser=special)
    db.add(p); db.commit(); db.refresh(p)
    return p


def _item(db, type_id=34, name="Tritanium", place_ids=None, user_id=1):
    it = TrackedItem(user_id=user_id, type_id=type_id, name=name, place_ids=place_ids or [])
    db.add(it); db.commit(); db.refresh(it)
    return it


def _price(db, type_id, place_id, *, buy, sell, vol, ago_h=0, user_id=1):
    ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=ago_h)
    db.add(TrackPrice(user_id=user_id, type_id=type_id, place_id=place_id,
                      timestamp=ts, buy=buy, sell=sell, volume=vol))
    db.commit()


# ── places ──────────────────────────────────────────────────────────────────

def test_add_and_list_places(db):
    out = run(tr.add_place(body=tr.PlaceCreate(kind="region", name="Jita", region_id=10000002),
                           current_user=USER, db=db))
    assert out.id and out.name == "Jita" and out.kind == "region"

    run(tr.add_place(body=tr.PlaceCreate(kind="system", name="Amarr", solar_system_id=30002187),
                     current_user=USER, db=db))
    listed = run(tr.list_places(current_user=USER, db=db))
    # ordered by name → Amarr before Jita
    assert [p.name for p in listed] == ["Amarr", "Jita"]


def test_add_place_enforces_max(db):
    for i in range(tr.MAX_PLACES):
        _place(db, name=f"P{i}")
    with pytest.raises(HTTPException) as ei:
        run(tr.add_place(body=tr.PlaceCreate(kind="region", name="Overflow"),
                         current_user=USER, db=db))
    assert ei.value.status_code == 400


def test_delete_place(db):
    p = _place(db)
    run(tr.del_place(place_id=p.id, current_user=USER, db=db))
    assert db.query(TrackedPlace).count() == 0


def test_delete_place_missing_404(db):
    with pytest.raises(HTTPException) as ei:
        run(tr.del_place(place_id=999, current_user=USER, db=db))
    assert ei.value.status_code == 404


# ── items ───────────────────────────────────────────────────────────────────

def test_add_and_list_items(db):
    p = _place(db)
    out = run(tr.add_item(body=tr.ItemCreate(type_id=34, name="Tritanium", place_ids=[p.id]),
                          current_user=USER, db=db))
    assert out.id and out.type_id == 34 and out.place_ids == [p.id]

    run(tr.add_item(body=tr.ItemCreate(type_id=35, name="Pyerite"), current_user=USER, db=db))
    listed = run(tr.list_items(current_user=USER, db=db))
    assert [it.name for it in listed] == ["Pyerite", "Tritanium"]  # ordered by name


def test_add_item_rejects_duplicate(db):
    _item(db, type_id=34)
    with pytest.raises(HTTPException) as ei:
        run(tr.add_item(body=tr.ItemCreate(type_id=34, name="Tritanium dup"),
                        current_user=USER, db=db))
    assert ei.value.status_code == 400 and "already" in ei.value.detail.lower()


def test_add_item_enforces_max(db, monkeypatch):
    # avoid seeding 100 rows: shrink the cap for this test
    monkeypatch.setattr(tr, "MAX_ITEMS", 2)
    _item(db, type_id=1); _item(db, type_id=2)
    with pytest.raises(HTTPException) as ei:
        run(tr.add_item(body=tr.ItemCreate(type_id=3, name="Third"), current_user=USER, db=db))
    assert ei.value.status_code == 400


def test_update_item_place_ids(db):
    p1, p2 = _place(db, name="A"), _place(db, name="B")
    it = _item(db, place_ids=[p1.id])
    out = run(tr.update_item(item_id=it.id, body=tr.ItemUpdate(place_ids=[p1.id, p2.id]),
                             current_user=USER, db=db))
    assert out.place_ids == [p1.id, p2.id]


def test_update_item_noop_when_place_ids_none(db):
    it = _item(db, place_ids=[7])
    out = run(tr.update_item(item_id=it.id, body=tr.ItemUpdate(place_ids=None),
                             current_user=USER, db=db))
    assert out.place_ids == [7]  # unchanged


def test_update_item_missing_404(db):
    with pytest.raises(HTTPException) as ei:
        run(tr.update_item(item_id=404, body=tr.ItemUpdate(place_ids=[1]),
                           current_user=USER, db=db))
    assert ei.value.status_code == 404


def test_delete_item(db):
    it = _item(db)
    run(tr.del_item(item_id=it.id, current_user=USER, db=db))
    assert db.query(TrackedItem).count() == 0


def test_delete_item_missing_404(db):
    with pytest.raises(HTTPException) as ei:
        run(tr.del_item(item_id=42, current_user=USER, db=db))
    assert ei.value.status_code == 404


# ── manual refresh (collector) ────────────────────────────────────────────────

def test_refresh_now_invokes_collector(db, monkeypatch):
    seen = {}

    def fake_collect(session, user_id):
        seen["user_id"] = user_id
        return 5

    monkeypatch.setattr(tr, "collect_for_user", fake_collect)
    out = run(tr.refresh_now(current_user=USER, db=db))
    assert out == {"stored": 5} and seen["user_id"] == 1


# ── item detail + indicators (price history read path) ─────────────────────────

def test_item_detail_builds_payload_from_history(db):
    p = _place(db)
    it = _item(db, type_id=34, place_ids=[p.id])
    # enough snapshots for the indicator window to produce something
    for h in range(12):
        _price(db, 34, p.id, buy=4.0 + h * 0.1, sell=5.0 + h * 0.1, vol=1000 + h, ago_h=12 - h)

    payload = run(tr.item_detail(item_id=it.id, place_id=p.id, window=5, refresh=True,
                                 current_user=USER, db=db))
    assert payload["item"]["type_id"] == 34
    assert payload["selected_place_id"] == p.id
    assert payload["window"] == 5
    meta = payload["places"][0]
    assert meta["place_id"] == p.id and meta["points"] == 12
    assert payload["indicators"] is not None


def test_item_detail_uses_cache_on_second_call(db, monkeypatch):
    p = _place(db)
    it = _item(db, type_id=34, place_ids=[p.id])
    for h in range(6):
        _price(db, 34, p.id, buy=4.0, sell=5.0, vol=1000, ago_h=6 - h)

    # first call (refresh=True) computes and stores the cache row
    run(tr.item_detail(item_id=it.id, place_id=p.id, window=5, refresh=True,
                       current_user=USER, db=db))

    # second call (refresh=False) must hit the cache, not the build path
    def boom(*a, **k):
        raise AssertionError("build_item_detail should not run on a cache hit")

    monkeypatch.setattr(tr.tracking_report, "build_item_detail", boom)
    cached = run(tr.item_detail(item_id=it.id, place_id=p.id, window=5, refresh=False,
                                current_user=USER, db=db))
    assert cached["item"]["type_id"] == 34


def test_item_detail_missing_404(db):
    with pytest.raises(HTTPException) as ei:
        run(tr.item_detail(item_id=777, current_user=USER, db=db))
    assert ei.value.status_code == 404


# ── allocate (warehouse sell decision) ─────────────────────────────────────────

def _patch_market(monkeypatch, *, region_buy=4.0, region_sell=5.0, hist_avg=4.0):
    """No-network market: Fuzzwork aggregates + ESI history + GNF local scrape."""
    monkeypatch.setattr(
        tr.market, "fuzzwork_aggregates_or_empty",
        lambda region, ids: {str(ids[0]): {"buy": {"max": region_buy},
                                            "sell": {"min": region_sell}}},
    )
    # 3 days of flat history → avg == hist_avg
    monkeypatch.setattr(
        tr.market, "esi_region_history",
        lambda region, type_id: [
            {"average": hist_avg, "lowest": hist_avg, "highest": hist_avg, "volume": 5000}
            for _ in range(3)
        ],
    )
    monkeypatch.setattr(tr.market, "gnf_local",
                        lambda type_id: {"buy": region_buy, "sell": region_sell})


def _patch_eve_volumes(monkeypatch, eve_db):
    """Point the router's EveSessionLocal at the in-memory eve DB (don't close it)."""
    eve_db.add(EveType(type_id=34, type_name="Tritanium", volume=0.01, published=True))
    eve_db.commit()
    monkeypatch.setattr(tr, "EveSessionLocal", lambda: _NoCloseSession(eve_db))


class _NoCloseSession:
    """Wrap the test eve session so the route's finally: close() is a no-op."""

    def __init__(self, sess):
        self._sess = sess

    def __getattr__(self, name):
        return getattr(self._sess, name)

    def close(self):
        pass


def test_allocate_returns_signal_and_allocations(db, eve_db, monkeypatch):
    p = _place(db, name="Jita", region_id=10000002)
    _patch_market(monkeypatch, region_buy=4.0, region_sell=5.0, hist_avg=4.0)
    _patch_eve_volumes(monkeypatch, eve_db)

    body = tr.AllocateRequest(
        items=[tr.AllocItem(type_id=34, name="Tritanium", quantity=1000, cost=3.0)],
        place_ids=[p.id], strategy="balanced", fees_pct=8.0,
        delivery_place_ids=[p.id],
    )
    out = run(tr.allocate(body=body, current_user=USER, db=db))
    assert out["strategy"] == "balanced"
    item = out["items"][0]
    assert item["type_id"] == 34
    # sell (5) >= 30d avg (4) → "sell" signal
    assert item["signal"] == "sell"
    assert item["venues"][0]["place_id"] == p.id
    assert item["allocations"]  # OR-Tools/heuristic produced at least one row
    assert item["total_profit"] is not None  # cost provided


def test_allocate_special_parser_place(db, eve_db, monkeypatch):
    p = _place(db, name="C-J", kind="system", region_id=None, special=True)
    _patch_market(monkeypatch, region_buy=4.0, region_sell=5.0)
    _patch_eve_volumes(monkeypatch, eve_db)

    body = tr.AllocateRequest(
        items=[tr.AllocItem(type_id=34, name="Tritanium", quantity=500)],
        place_ids=[p.id], strategy="fast",
    )
    out = run(tr.allocate(body=body, current_user=USER, db=db))
    venue = out["items"][0]["venues"][0]
    assert venue["special"] is True
    # special place has no region_id → empty history → neutral signal
    assert out["items"][0]["signal"] == "neutral"
    assert out["items"][0]["total_profit"] is None  # no cost basis


def test_allocate_handles_empty_history_and_unparseable_price(db, eve_db, monkeypatch):
    """Region place with no history rows → _hist_stats([]) all-None;
    non-numeric Fuzzwork prices → the float() fallback returns None."""
    p = _place(db, name="Jita", region_id=10000002)
    # prices that can't be cast to float exercise the inner f() except branch
    monkeypatch.setattr(
        tr.market, "fuzzwork_aggregates_or_empty",
        lambda region, ids: {str(ids[0]): {"buy": {"max": "n/a"}, "sell": {"min": None}}},
    )
    monkeypatch.setattr(tr.market, "esi_region_history", lambda region, type_id: [])
    _patch_eve_volumes(monkeypatch, eve_db)

    body = tr.AllocateRequest(
        items=[tr.AllocItem(type_id=34, name="Tritanium", quantity=100)],
        place_ids=[p.id], strategy="balanced",
    )
    out = run(tr.allocate(body=body, current_user=USER, db=db))
    venue = out["items"][0]["venues"][0]
    assert venue["buy"] is None and venue["sell"] is None
    assert venue["hist"] == {"avg": None, "min": None, "max": None, "vol": None}
    assert out["items"][0]["signal"] == "neutral"  # no sellable venue


def test_allocate_requires_a_place(db):
    with pytest.raises(HTTPException) as ei:
        run(tr.allocate(body=tr.AllocateRequest(items=[], place_ids=[]),
                        current_user=USER, db=db))
    assert ei.value.status_code == 400


# ── user scoping ───────────────────────────────────────────────────────────────

def test_lists_are_scoped_to_current_user(db):
    _place(db, name="Mine", user_id=1)
    _place(db, name="Theirs", user_id=2)
    _item(db, type_id=34, name="MineItem", user_id=1)
    _item(db, type_id=35, name="TheirItem", user_id=2)

    places = run(tr.list_places(current_user=USER, db=db))
    items = run(tr.list_items(current_user=USER, db=db))
    assert [p.name for p in places] == ["Mine"]
    assert [i.name for i in items] == ["MineItem"]
