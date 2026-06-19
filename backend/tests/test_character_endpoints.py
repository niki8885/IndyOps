"""
Character-page endpoints (Personal File): mining journal + tax write-offs,
journal settings, industry job slots, asset-location resolution, overview and
standings. Driven against in-memory SQLite the project's no-HTTP way — the async
endpoint functions are called directly with seeded sessions; market + name-
resolution I/O is monkeypatched so no network is touched.
"""
import asyncio
import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import characters_router as cr
from app.core.database import (
    Base, LinkedCharacter, EsiSkill, EsiAsset, EsiMiningLedger, EsiIndustryJob,
    EsiStanding, CharacterSettings,
)
from app.core.database_eve import EveBase, EveType, EveGroup, EveTypeMaterial, EveStation, EveSolarSystem

CID = 99
USER = SimpleNamespace(id=1)


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


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    # Jita prices: Tritanium (34) sells at 5, buys at 4.
    monkeypatch.setattr(cr.market, "fuzzwork_aggregates_or_empty",
                        lambda region, ids: {"34": {"buy": {"max": 4.0}, "sell": {"min": 5.0}}})
    monkeypatch.setattr(cr.esi, "resolve_names", lambda ids: {})


def _seed_char(app_db, scopes="esi-industry.read_character_mining.v1"):
    app_db.add(LinkedCharacter(id=1, user_id=1, character_id=CID, character_name="Miner",
                               scopes=scopes, is_active=True, status="active"))
    app_db.commit()


def _seed_veldspar(eve_db):
    # one ore (asteroid category 25) reprocessing to Tritanium
    eve_db.add_all([
        EveGroup(group_id=450, category_id=25, group_name="Veldspar"),
        EveType(type_id=1230, type_name="Veldspar", group_id=450, volume=0.1, portion_size=100, published=True),
        EveType(type_id=34, type_name="Tritanium", group_id=18, volume=0.01, published=True),
        EveTypeMaterial(type_id=1230, material_type_id=34, quantity=400),
    ])
    eve_db.commit()


def _mine(app_db, qty=10000):
    app_db.add(EsiMiningLedger(character_id=CID, date=datetime.datetime.now(datetime.timezone.utc).date(),
                               type_id=1230, solar_system_id=30000142, quantity=qty))
    app_db.commit()


# ── settings ─────────────────────────────────────────────────────────────────

def test_settings_default_and_update(app_db):
    _seed_char(app_db)
    assert run(cr.get_settings(char_id=1, current_user=USER, db=app_db)) == {
        "mining_tax_pct": 0.0, "price_basis": "sell", "refine_base_yield": 0.5}

    upd = run(cr.put_settings(char_id=1, current_user=USER, db=app_db,
                              body=cr.SettingsIn(mining_tax_pct=10, price_basis="buy", refine_base_yield=0.5)))
    assert upd["mining_tax_pct"] == 10 and upd["price_basis"] == "buy"
    assert run(cr.get_settings(char_id=1, current_user=USER, db=app_db))["mining_tax_pct"] == 10


def test_settings_rejects_bad_basis(app_db):
    _seed_char(app_db)
    with pytest.raises(Exception):
        run(cr.put_settings(char_id=1, current_user=USER, db=app_db,
                            body=cr.SettingsIn(price_basis="midpoint")))


# ── mining journal (refine → Jita value → tax) ───────────────────────────────

def test_mining_journal_refines_values_and_taxes(app_db, eve_db):
    _seed_char(app_db); _seed_veldspar(eve_db); _mine(app_db, 10000)
    app_db.add(CharacterSettings(character_id=CID, mining_tax_pct=10.0, price_basis="sell", refine_base_yield=0.5))
    app_db.commit()

    j = run(cr.get_mining_journal(char_id=1, period="month", offset=0, scope="character",
                                  basis=None, current_user=USER, db=app_db, eve_db=eve_db))
    # 10000 Veldspar = 100 batches × 400 Trit = 40000 perfect × 0.5 yield = 20000 × 5 ISK
    assert j["categories"]["ore"]["value"] == pytest.approx(100000.0)
    assert j["categories"]["ore"]["qty"] == 10000
    assert j["gross_value"] == pytest.approx(100000.0)
    assert j["tax_pct"] == pytest.approx(10.0)
    assert j["tax_amount"] == pytest.approx(10000.0)
    assert j["net_value"] == pytest.approx(90000.0)
    assert j["stats_30d"]["total"] == pytest.approx(100000.0)
    assert j["items"][0]["name"] == "Veldspar"
    assert j["written_off"] is False
    assert j["period"]["key"]  # e.g. 2026-06


def test_mining_journal_empty_period(app_db, eve_db):
    _seed_char(app_db); _seed_veldspar(eve_db); _mine(app_db, 10000)
    # the previous year has no ledger rows
    j = run(cr.get_mining_journal(char_id=1, period="year", offset=-1, scope="character",
                                  basis="sell", current_user=USER, db=app_db, eve_db=eve_db))
    assert j["gross_value"] == pytest.approx(0.0)
    assert j["items"] == []


# ── mining ledger (raw chronological entries) ─────────────────────────────────

def test_mining_ledger_lists_entries_newest_first(app_db, eve_db):
    _seed_char(app_db); _seed_veldspar(eve_db)
    eve_db.add(EveSolarSystem(solar_system_id=30000142, solar_system_name="Jita"))
    eve_db.commit()
    today = datetime.datetime.now(datetime.timezone.utc).date()
    app_db.add_all([
        EsiMiningLedger(character_id=CID, date=today - datetime.timedelta(days=2),
                        type_id=1230, solar_system_id=30000142, quantity=5000),
        EsiMiningLedger(character_id=CID, date=today,
                        type_id=1230, solar_system_id=30000142, quantity=12000),
    ])
    app_db.commit()

    out = run(cr.get_mining_ledger(char_id=1, period=None, offset=0, scope="character",
                                   limit=500, current_user=USER, db=app_db, eve_db=eve_db))
    assert out["count"] == 2
    assert out["total_quantity"] == 17000
    assert out["period"] is None
    # newest first
    assert out["entries"][0]["date"] == today.isoformat()
    assert out["entries"][0]["quantity"] == 12000
    assert out["entries"][0]["name"] == "Veldspar"
    assert out["entries"][0]["category"] == "ore"
    assert out["entries"][0]["system_name"] == "Jita"


def test_mining_ledger_period_filter(app_db, eve_db):
    _seed_char(app_db); _seed_veldspar(eve_db); _mine(app_db, 8000)
    # this year has the row, the previous year does not
    cur = run(cr.get_mining_ledger(char_id=1, period="year", offset=0, scope="character",
                                   limit=500, current_user=USER, db=app_db, eve_db=eve_db))
    assert cur["count"] == 1 and cur["period"]["key"]
    prev = run(cr.get_mining_ledger(char_id=1, period="year", offset=-1, scope="character",
                                    limit=500, current_user=USER, db=app_db, eve_db=eve_db))
    assert prev["count"] == 0 and prev["entries"] == []


# ── tax write-off (persisted) ────────────────────────────────────────────────

def test_writeoff_persists_then_undo(app_db, eve_db):
    _seed_char(app_db); _seed_veldspar(eve_db); _mine(app_db, 10000)

    rec = run(cr.writeoff_tax(char_id=1, current_user=USER, db=app_db, eve_db=eve_db,
                              body=cr.WriteoffIn(period="month", offset=0, scope="character")))
    assert rec["id"] and rec["net_value"] == pytest.approx(100000.0)  # default tax 0 → net = gross

    j = run(cr.get_mining_journal(char_id=1, period="month", offset=0, scope="character",
                                  basis=None, current_user=USER, db=app_db, eve_db=eve_db))
    assert j["written_off"] is True and j["writeoff"]["id"] == rec["id"]

    run(cr.undo_writeoff(char_id=1, period="month", offset=0, scope="character",
                         current_user=USER, db=app_db))
    j2 = run(cr.get_mining_journal(char_id=1, period="month", offset=0, scope="character",
                                   basis=None, current_user=USER, db=app_db, eve_db=eve_db))
    assert j2["written_off"] is False


# ── industry job slots ───────────────────────────────────────────────────────

def test_industry_jobs_slots_from_skills(app_db, eve_db):
    _seed_char(app_db)
    app_db.add(EsiSkill(character_id=CID, skill_id=3387, trained_level=5))  # Mass Production → +5
    app_db.add(EsiIndustryJob(character_id=CID, job_id=1, activity_id=1, product_type_id=34,
                              runs=1, status="active"))
    app_db.commit()

    out = run(cr.get_industry_jobs(char_id=1, current_user=USER, db=app_db, eve_db=eve_db))
    assert out["slots"]["manufacturing"] == {"used": 1, "max": 6}   # 1 base + 5
    assert out["slots"]["science"] == {"used": 0, "max": 1}
    assert len(out["jobs"]) == 1


# ── asset location resolution ────────────────────────────────────────────────

def test_assets_resolve_station_name(app_db, eve_db):
    _seed_char(app_db)
    eve_db.add_all([
        EveType(type_id=34, type_name="Tritanium", group_id=18, volume=0.01, published=True),
        EveStation(station_id=60003760, station_name="Jita IV - Moon 4 - CNAP", solar_system_id=30000142),
    ])
    eve_db.commit()
    app_db.add(EsiAsset(character_id=CID, item_id=1, type_id=34, quantity=5,
                        location_id=60003760, location_type="station", location_flag="Hangar"))
    app_db.commit()

    rows = run(cr.get_assets(char_id=1, current_user=USER, db=app_db, eve_db=eve_db))
    assert rows[0]["type_name"] == "Tritanium"
    assert rows[0]["location_name"] == "Jita IV - Moon 4 - CNAP"


# ── overview + standings smoke ───────────────────────────────────────────────

def test_overview_smoke(app_db, eve_db):
    _seed_char(app_db)
    o = run(cr.get_overview(char_id=1, current_user=USER, db=app_db, eve_db=eve_db))
    assert o["character_id"] == CID
    assert o["wealth"]["liquid"] is None
    # only the mining scope was granted → location + implants scopes still missing
    assert set(o["missing_scopes"]) == {"esi-location.read_location.v1", "esi-clones.read_implants.v1"}


def test_standings_returns_rows(app_db):
    _seed_char(app_db)
    app_db.add(EsiStanding(character_id=CID, from_id=500001, from_type="faction", standing=7.5))
    app_db.commit()
    rows = run(cr.get_standings(char_id=1, current_user=USER, db=app_db))
    assert rows[0]["from_id"] == 500001 and rows[0]["standing"] == pytest.approx(7.5)
