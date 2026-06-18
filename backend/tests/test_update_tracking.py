"""
Unit tests for the price-tracking collector job (``app.tasks.update_tracking``).

In-memory SQLite, no network: ``market.fuzzwork_aggregates_or_empty`` and
``market.gnf_local`` are monkeypatched on the task module. ``collect_for_user``
takes a session directly; ``run_tracking_update`` opens its own ``SessionLocal``,
which we patch to hand back the seeded session.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, TrackedPlace, TrackedItem, TrackPrice
from app.tasks import update_tracking as ut

REGION = 10000002  # The Forge


def _mem_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        TrackedPlace.__table__, TrackedItem.__table__, TrackPrice.__table__])
    return sessionmaker(bind=engine)(), engine


@pytest.fixture
def db():
    session, engine = _mem_session()
    yield session
    session.close()
    engine.dispose()


def _seed_region_place(db, user_id=1, place_id=1):
    db.add(TrackedPlace(id=place_id, user_id=user_id, kind="region", name="The Forge",
                        region_id=REGION, special_parser=False))
    db.commit()


def _seed_special_place(db, user_id=1, place_id=2):
    db.add(TrackedPlace(id=place_id, user_id=user_id, kind="system", name="C-J6MT",
                        region_id=None, special_parser=True))
    db.commit()


def _seed_item(db, user_id=1, item_id=1, type_id=34, place_ids=(1,)):
    db.add(TrackedItem(id=item_id, user_id=user_id, type_id=type_id, name="Tritanium",
                       place_ids=list(place_ids)))
    db.commit()


# ── _fnum helper ──────────────────────────────────────────────────────────────

def test_fnum():
    assert ut._fnum("3.5") == pytest.approx(3.5)
    assert ut._fnum(None) is None
    assert ut._fnum("nope") is None


# ── collect_for_user: region (fuzzwork) path ──────────────────────────────────

def test_collect_for_user_region(monkeypatch, db):
    _seed_region_place(db)
    _seed_item(db, type_id=34, place_ids=(1,))
    monkeypatch.setattr(ut.market, "fuzzwork_aggregates_or_empty",
                        lambda region, ids: {"34": {"buy": {"max": 4.0},
                                                    "sell": {"min": 5.0, "volume": 1000}}})

    stored = ut.collect_for_user(db, user_id=1)
    assert stored == 1
    row = db.query(TrackPrice).one()
    assert row.type_id == 34 and row.place_id == 1
    assert row.buy == pytest.approx(4.0)
    assert row.sell == pytest.approx(5.0)
    assert row.volume == pytest.approx(1000.0)


# ── collect_for_user: special-parser (gnf scrape) path ────────────────────────

def test_collect_for_user_special_parser(monkeypatch, db):
    _seed_special_place(db, place_id=2)
    _seed_item(db, type_id=34, place_ids=(2,))
    monkeypatch.setattr(ut.market, "gnf_local",
                        lambda tid: {"buy": 4.2, "sell": 6.1})
    # fuzzwork must not be needed for a special place — make it loud if called
    monkeypatch.setattr(ut.market, "fuzzwork_aggregates_or_empty",
                        lambda *a, **k: pytest.fail("fuzzwork should not be called"))

    stored = ut.collect_for_user(db, user_id=1)
    assert stored == 1
    row = db.query(TrackPrice).one()
    assert row.buy == pytest.approx(4.2) and row.sell == pytest.approx(6.1)
    assert row.volume is None


def test_collect_for_user_special_parser_none(monkeypatch, db):
    # gnf returns nothing → both buy & sell None → row skipped
    _seed_special_place(db, place_id=2)
    _seed_item(db, type_id=34, place_ids=(2,))
    monkeypatch.setattr(ut.market, "gnf_local", lambda tid: None)
    assert ut.collect_for_user(db, user_id=1) == 0
    assert db.query(TrackPrice).count() == 0


# ── empty-input branches ──────────────────────────────────────────────────────

def test_collect_for_user_no_places(monkeypatch, db):
    _seed_item(db, place_ids=(1,))  # item references a place that doesn't exist
    assert ut.collect_for_user(db, user_id=1) == 0


def test_collect_for_user_no_items(monkeypatch, db):
    _seed_region_place(db)
    assert ut.collect_for_user(db, user_id=1) == 0


def test_collect_for_user_skips_unknown_place_id(monkeypatch, db):
    _seed_region_place(db, place_id=1)
    # item points at place 1 (known) and 99 (unknown) → only the known one yields a row
    _seed_item(db, type_id=34, place_ids=(1, 99))
    monkeypatch.setattr(ut.market, "fuzzwork_aggregates_or_empty",
                        lambda region, ids: {"34": {"buy": {"max": 4.0},
                                                    "sell": {"min": 5.0, "volume": 1}}})
    assert ut.collect_for_user(db, user_id=1) == 1


def test_collect_for_user_skips_empty_aggregate(monkeypatch, db):
    # region returns nothing for the type → buy & sell None → skipped
    _seed_region_place(db)
    _seed_item(db, type_id=34, place_ids=(1,))
    monkeypatch.setattr(ut.market, "fuzzwork_aggregates_or_empty", lambda region, ids: {})
    assert ut.collect_for_user(db, user_id=1) == 0
    assert db.query(TrackPrice).count() == 0


# ── run_tracking_update (job entry point) ─────────────────────────────────────

def test_run_tracking_update(monkeypatch, db):
    _seed_region_place(db)
    _seed_item(db, type_id=34, place_ids=(1,))
    db.add(TrackedItem(id=2, user_id=1, type_id=35, name="Pyerite", place_ids=[1]))
    db.commit()
    monkeypatch.setattr(ut, "SessionLocal", lambda: db)
    monkeypatch.setattr(ut.market, "fuzzwork_aggregates_or_empty",
                        lambda region, ids: {str(t): {"buy": {"max": 4.0},
                                                      "sell": {"min": 5.0, "volume": 7}} for t in ids})

    summary = ut.run_tracking_update()
    assert summary["users"] == 1
    assert summary["rows"] == 2
    assert db.query(TrackPrice).count() == 2


def test_run_tracking_update_no_users(monkeypatch, db):
    monkeypatch.setattr(ut, "SessionLocal", lambda: db)
    summary = ut.run_tracking_update()
    assert summary == {"users": 0, "rows": 0}


def test_run_tracking_update_swallows_per_user_error(monkeypatch, db):
    _seed_region_place(db)
    _seed_item(db, type_id=34, place_ids=(1,))
    monkeypatch.setattr(ut, "SessionLocal", lambda: db)

    def boom(_db, _uid):
        raise RuntimeError("collect blew up")
    monkeypatch.setattr(ut, "collect_for_user", boom)

    # the error is logged + rolled back, not raised; the job still returns a summary
    summary = ut.run_tracking_update()
    assert summary == {"users": 0, "rows": 0}
