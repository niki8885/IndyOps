"""
Unit tests for the ESI character-sync job (``app.tasks.update_esi``).

This is the big collector: ``sync_character`` pulls every per-endpoint feed
(wallet/skills/assets/location/implants/mining/structures/contracts/jobs/
standings/wealth) and persists it, while ``sync_all_active`` loops over active
linked characters.

Everything is driven against in-memory SQLite with **no network and no token
crypto**: ``esi.valid_access_token`` is patched to return a dummy token and every
``esi.fetch_*`` call is monkeypatched on the task module. The PostgreSQL
``ON CONFLICT`` upserts compile + run fine on SQLite under SQLAlchemy 2.0, so the
real ``_upsert``/``_replace`` code paths are exercised.
"""
import datetime

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import (
    Base, LinkedCharacter, EsiWalletTransaction, EsiSkill, EsiAsset, EsiContract,
    EsiIndustryJob, EsiStanding, EsiStructure, EsiImplant, EsiMiningLedger,
    EsiBlueprintCopy, CharacterWealthSnapshot,
)
from app.tasks import update_esi as ue

CID = 90000001

_ESI_TABLES = [
    LinkedCharacter, EsiWalletTransaction, EsiSkill, EsiAsset, EsiContract,
    EsiIndustryJob, EsiStanding, EsiStructure, EsiImplant, EsiMiningLedger,
    EsiBlueprintCopy, CharacterWealthSnapshot,
]

# every scope the task gates on, so the optional endpoints all run
_ALL_SCOPES = " ".join([
    ue._STRUCTURE_SCOPE, ue._LOCATION_SCOPE, ue._SHIP_SCOPE, ue._ONLINE_SCOPE,
    ue._IMPLANTS_SCOPE, ue._MINING_SCOPE,
])


def _mem_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[m.__table__ for m in _ESI_TABLES])
    return sessionmaker(bind=engine)(), engine


@pytest.fixture
def db():
    session, engine = _mem_session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def _reset_price_cache():
    # the module-level price cache leaks across tests otherwise
    ue._price_cache["prices"] = None
    ue._price_cache["ts"] = None
    yield
    ue._price_cache["prices"] = None
    ue._price_cache["ts"] = None


def _seed_char(db, scopes=_ALL_SCOPES, **kw):
    char = LinkedCharacter(
        id=1, user_id=1, character_id=CID, character_name="Pilot",
        scopes=scopes, is_active=True, status="active", **kw)
    db.add(char)
    db.commit()
    return char


def _patch_token(monkeypatch):
    monkeypatch.setattr(ue.esi, "valid_access_token", lambda db, char: "tok-123")


def _patch_all_esi(monkeypatch, **overrides):
    """Patch every esi.fetch_* the task uses with sensible empty/default returns,
    then apply per-test overrides."""
    defaults = {
        "fetch_affiliation": lambda cid: {"corporation_id": 1000, "alliance_id": 99000},
        "fetch_corporation": lambda corp_id: {"name": "Test Corp"},
        "fetch_alliance": lambda all_id: {"name": "Test Alliance"},
        "fetch_wallet_balance": lambda cid, tok: 1_000_000.0,
        "fetch_transactions": lambda cid, tok: [],
        "fetch_skills": lambda cid, tok: {"total_sp": 0, "skills": []},
        "fetch_assets": lambda cid, tok: [],
        "fetch_location": lambda cid, tok: {"solar_system_id": 30000142},
        "fetch_ship": lambda cid, tok: {"ship_type_id": 670, "ship_name": "Pod"},
        "fetch_online": lambda cid, tok: {"online": True, "last_login": None},
        "fetch_implants": lambda cid, tok: [],
        "fetch_mining": lambda cid, tok: [],
        "fetch_structure": lambda sid, tok: {"name": "Citadel", "solar_system_id": 30000142, "type_id": 35832},
        "fetch_contracts": lambda cid, tok: [],
        "fetch_industry_jobs": lambda cid, tok: [],
        "fetch_standings": lambda cid, tok: [],
        "fetch_market_prices": lambda: [],
    }
    defaults.update(overrides)
    for name, fn in defaults.items():
        monkeypatch.setattr(ue.esi, name, fn)
    # parse_dt is a pure helper; keep the real one


# ── _has_scope ────────────────────────────────────────────────────────────────

def test_has_scope():
    char = LinkedCharacter(scopes="a b c")
    assert ue._has_scope(char, "b") is True
    assert ue._has_scope(char, "z") is False
    assert ue._has_scope(LinkedCharacter(scopes=None), "a") is False


# ── _market_prices (module-level cache) ───────────────────────────────────────

def test_market_prices_builds_and_caches(monkeypatch):
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return [{"type_id": 34, "average_price": 5.0},
                {"type_id": 35, "adjusted_price": 3.0}]  # falls back to adjusted
    monkeypatch.setattr(ue.esi, "fetch_market_prices", fetch)

    prices = ue._market_prices()
    assert prices == {34: 5.0, 35: 3.0}
    # second call is served from cache (fetch not called again)
    ue._market_prices()
    assert calls["n"] == 1


def test_market_prices_failure_returns_empty(monkeypatch):
    def boom():
        raise RuntimeError("esi down")
    monkeypatch.setattr(ue.esi, "fetch_market_prices", boom)
    assert ue._market_prices() == {}


# ── row mappers ───────────────────────────────────────────────────────────────

def test_row_mappers():
    tx = ue._map_transaction(CID, {"transaction_id": 1, "type_id": 34, "quantity": 2,
                                   "unit_price": 5.0, "is_buy": True, "date": "2026-01-01T00:00:00Z"})
    assert tx["character_id"] == CID and tx["transaction_id"] == 1
    assert tx["date"] == datetime.datetime(2026, 1, 1)

    sk = ue._map_skill(CID, {"skill_id": 3300, "skillpoints_in_skill": 256000,
                             "trained_skill_level": 5, "active_skill_level": 5})
    assert sk["skill_id"] == 3300 and sk["skillpoints"] == 256000

    a = ue._map_asset(CID, {"item_id": 7, "type_id": 34, "quantity": 9, "location_id": 60003760})
    assert a["item_id"] == 7 and a["location_id"] == 60003760

    c = ue._map_contract(CID, {"contract_id": 5, "type": "item_exchange", "status": "outstanding"})
    assert c["contract_id"] == 5 and c["status"] == "outstanding"

    s = ue._map_standing(CID, {"from_id": 500001, "from_type": "faction", "standing": 5.0})
    assert s["from_id"] == 500001

    j = ue._map_job(CID, {"job_id": 11, "activity_id": 1, "runs": 3, "status": "active"})
    assert j["job_id"] == 11 and j["runs"] == 3


# ── _upsert / _replace ────────────────────────────────────────────────────────

def test_upsert_empty_is_noop(db):
    ue._upsert(db, EsiSkill, [], ["character_id", "skill_id"], ["skillpoints"])
    assert db.query(EsiSkill).count() == 0


def test_upsert_then_update(db):
    row = {"character_id": CID, "skill_id": 3300, "skillpoints": 1, "trained_level": 1, "active_level": 1}
    ue._upsert(db, EsiSkill, [row], ["character_id", "skill_id"],
               ["skillpoints", "trained_level", "active_level"])
    ue._upsert(db, EsiSkill, [{**row, "skillpoints": 999}], ["character_id", "skill_id"],
               ["skillpoints", "trained_level", "active_level"])
    rows = db.query(EsiSkill).all()
    assert len(rows) == 1 and rows[0].skillpoints == 999


def test_replace_swaps_set(db):
    ue._replace(db, EsiImplant, CID, [{"character_id": CID, "type_id": 10}])
    ue._replace(db, EsiImplant, CID, [{"character_id": CID, "type_id": 20},
                                      {"character_id": CID, "type_id": 21}])
    type_ids = sorted(r.type_id for r in db.query(EsiImplant).all())
    assert type_ids == [20, 21]


# ── _resolve_structures ───────────────────────────────────────────────────────

def test_resolve_structures_empty_returns_zero(db):
    assert ue._resolve_structures(db, "tok", set()) == 0
    assert ue._resolve_structures(db, "tok", {None}) == 0


def test_resolve_structures_success(monkeypatch, db):
    monkeypatch.setattr(ue.esi, "fetch_structure",
                        lambda sid, tok: {"name": "Sotiyo", "solar_system_id": 30000142, "type_id": 35827})
    resolved = ue._resolve_structures(db, "tok", {1234567890123})
    assert resolved == 1
    row = db.query(EsiStructure).one()
    assert row.name == "Sotiyo" and row.error is None


def test_resolve_structures_403_records_forbidden(monkeypatch, db):
    resp = requests.Response()
    resp.status_code = 403

    def boom(sid, tok):
        raise requests.HTTPError(response=resp)
    monkeypatch.setattr(ue.esi, "fetch_structure", boom)

    resolved = ue._resolve_structures(db, "tok", {999})
    assert resolved == 0  # no name resolved
    row = db.query(EsiStructure).one()
    assert row.name is None and row.error == "forbidden"


def test_resolve_structures_404_records_not_found(monkeypatch, db):
    resp = requests.Response()
    resp.status_code = 404

    def boom(sid, tok):
        raise requests.HTTPError(response=resp)
    monkeypatch.setattr(ue.esi, "fetch_structure", boom)

    ue._resolve_structures(db, "tok", {888})
    assert db.query(EsiStructure).one().error == "not_found"


def test_resolve_structures_other_http_error(monkeypatch, db):
    # a 5xx (not 403/404/422) → generic 'error'
    resp = requests.Response()
    resp.status_code = 500

    def boom(sid, tok):
        raise requests.HTTPError(response=resp)
    monkeypatch.setattr(ue.esi, "fetch_structure", boom)
    ue._resolve_structures(db, "tok", {666})
    assert db.query(EsiStructure).one().error == "error"


def test_resolve_structures_generic_error(monkeypatch, db):
    def boom(sid, tok):
        raise ValueError("weird")
    monkeypatch.setattr(ue.esi, "fetch_structure", boom)
    ue._resolve_structures(db, "tok", {777})
    assert db.query(EsiStructure).one().error == "error"


def test_resolve_structures_skips_fresh_name(monkeypatch, db):
    # a fresh, named row is left alone — fetch_structure must not be called
    db.add(EsiStructure(structure_id=555, name="Cached", solar_system_id=30000142,
                        updated_at=ue.utcnow()))
    db.commit()
    monkeypatch.setattr(ue.esi, "fetch_structure",
                        lambda *a, **k: pytest.fail("should not refetch a fresh name"))
    assert ue._resolve_structures(db, "tok", {555}) == 0


def test_resolve_structures_skips_recent_failure(monkeypatch, db):
    db.add(EsiStructure(structure_id=556, name=None, error="forbidden", updated_at=ue.utcnow()))
    db.commit()
    monkeypatch.setattr(ue.esi, "fetch_structure",
                        lambda *a, **k: pytest.fail("should back off on a recent failure"))
    assert ue._resolve_structures(db, "tok", {556}) == 0


# ── _asset_structure_ids ──────────────────────────────────────────────────────

def test_asset_structure_ids(db):
    # an item parked directly in an Upwell structure (location_type 'item' with a
    # parent not in the asset list resolves to a structure terminus)
    db.add(EsiAsset(character_id=CID, item_id=1, type_id=34, quantity=1,
                    location_id=1234567890123, location_type="item"))
    db.commit()
    ids = ue._asset_structure_ids(db, CID)
    assert ids == {1234567890123}


# ── sync_character — full success path ────────────────────────────────────────

def test_sync_character_success(monkeypatch, db):
    char = _seed_char(db)
    _patch_token(monkeypatch)
    _patch_all_esi(
        monkeypatch,
        fetch_transactions=lambda cid, tok: [
            {"transaction_id": 1, "type_id": 34, "quantity": 5, "unit_price": 5.0,
             "is_buy": True, "date": "2026-01-01T12:00:00Z"}],
        fetch_skills=lambda cid, tok: {"total_sp": 5_000_000,
                                       "skills": [{"skill_id": 3300, "skillpoints_in_skill": 256000,
                                                   "trained_skill_level": 5, "active_skill_level": 5}]},
        fetch_assets=lambda cid, tok: [{"item_id": 7, "type_id": 34, "quantity": 100,
                                        "location_id": 60003760, "location_type": "station"}],
        fetch_location=lambda cid, tok: {"solar_system_id": 30000142, "station_id": 60003760},
        fetch_implants=lambda cid, tok: [10, 20],
        fetch_mining=lambda cid, tok: [{"date": "2026-01-01", "type_id": 1230,
                                        "solar_system_id": 30000142, "quantity": 5000}],
        fetch_contracts=lambda cid, tok: [{"contract_id": 5, "type": "item_exchange",
                                           "status": "outstanding"}],
        fetch_industry_jobs=lambda cid, tok: [{"job_id": 11, "activity_id": 1, "runs": 1,
                                               "status": "active"}],
        fetch_standings=lambda cid, tok: [{"from_id": 500001, "from_type": "faction", "standing": 5.0}],
        fetch_market_prices=lambda: [{"type_id": 34, "average_price": 6.0}],
    )

    summary = ue.sync_character(db, char)

    assert summary["character_id"] == CID
    assert summary["errors"] == []
    counts = summary["counts"]
    assert counts["affiliation"] == 1
    assert counts["wallet"] == 1
    assert counts["skills"] == 1
    assert counts["assets"] == 1
    assert counts["location"] == 1
    assert counts["implants"] == 2
    assert counts["mining"] == 1
    assert counts["contracts"] == 1
    assert counts["industry_jobs"] == 1
    assert counts["standings"] == 1
    assert counts["wealth"] == 1

    # persisted rows
    assert db.query(EsiWalletTransaction).count() == 1
    assert db.query(EsiSkill).count() == 1
    assert db.query(EsiAsset).count() == 1
    assert sorted(r.type_id for r in db.query(EsiImplant).all()) == [10, 20]
    assert db.query(EsiMiningLedger).count() == 1
    assert db.query(EsiContract).count() == 1
    assert db.query(EsiIndustryJob).count() == 1
    assert db.query(EsiStanding).count() == 1

    # char fields written
    assert char.corporation_id == 1000
    assert char.corporation_name == "Test Corp"
    assert char.alliance_name == "Test Alliance"
    assert char.wallet_balance == pytest.approx(1_000_000.0)
    assert char.total_sp == 5_000_000
    assert char.location_id == 60003760 and char.location_type == "station"
    assert char.last_sync_at is not None

    # wealth: 100 units * 6.0 average = 600; total = liquid + assets
    wealth = db.query(CharacterWealthSnapshot).one()
    assert wealth.assets_value == pytest.approx(600.0)
    assert wealth.liquid == pytest.approx(1_000_000.0)
    assert wealth.total == pytest.approx(1_000_600.0)
    assert char.assets_value == pytest.approx(600.0)


# ── sync_character — scope gating ─────────────────────────────────────────────

def test_sync_character_skips_scoped_endpoints(monkeypatch, db):
    # only the wallet/skills/assets feeds need no scope here; the gated ones return 0
    char = _seed_char(db, scopes="")  # no optional scopes
    _patch_token(monkeypatch)
    _patch_all_esi(monkeypatch,
                   fetch_location=lambda cid, tok: pytest.fail("location is scope-gated"),
                   fetch_implants=lambda cid, tok: pytest.fail("implants is scope-gated"),
                   fetch_mining=lambda cid, tok: pytest.fail("mining is scope-gated"),
                   fetch_structure=lambda *a, **k: pytest.fail("structures is scope-gated"))

    summary = ue.sync_character(db, char)
    assert summary["counts"]["location"] == 0
    assert summary["counts"]["implants"] == 0
    assert summary["counts"]["mining"] == 0
    assert summary["counts"]["structures"] == 0
    assert summary["errors"] == []


# ── sync_character — structure resolution from assets + location ──────────────

def test_sync_character_resolves_structures(monkeypatch, db):
    char = _seed_char(db)
    _patch_token(monkeypatch)
    _patch_all_esi(
        monkeypatch,
        # asset parked in a structure (item pointing at a non-owned parent)
        fetch_assets=lambda cid, tok: [{"item_id": 1, "type_id": 34, "quantity": 1,
                                        "location_id": 1234567890123, "location_type": "item"}],
        # docked in a different structure
        fetch_location=lambda cid, tok: {"solar_system_id": 30000142, "structure_id": 9876543210987},
    )
    seen = {}
    monkeypatch.setattr(ue.esi, "fetch_structure",
                        lambda sid, tok: seen.setdefault(sid, {"name": f"S{sid}",
                                                               "solar_system_id": 30000142, "type_id": 35832}))

    summary = ue.sync_character(db, char)
    # both the asset structure and the docked structure were resolved
    assert summary["counts"]["structures"] == 2
    resolved_ids = {r.structure_id for r in db.query(EsiStructure).all()}
    assert {1234567890123, 9876543210987} <= resolved_ids


# ── sync_character — per-endpoint error captured, not raised ──────────────────

def test_sync_character_endpoint_error_captured(monkeypatch, db):
    char = _seed_char(db)
    _patch_token(monkeypatch)
    _patch_all_esi(monkeypatch,
                   fetch_wallet_balance=lambda cid, tok: (_ for _ in ()).throw(RuntimeError("wallet 500")))

    summary = ue.sync_character(db, char)
    # the wallet step failed but the job continued and recorded the error
    assert any("wallet" in e and "wallet 500" in e for e in summary["errors"])
    assert "wallet" not in summary["counts"]
    assert summary["counts"]["skills"] == 0  # other steps still ran
    assert char.last_sync_at is not None


def test_sync_character_optional_subfetch_failures_are_swallowed(monkeypatch, db):
    # ship/online/corp-name/alliance-name fetches fail → swallowed, sync still ok
    char = _seed_char(db)
    _patch_token(monkeypatch)
    _patch_all_esi(
        monkeypatch,
        fetch_corporation=lambda corp_id: (_ for _ in ()).throw(RuntimeError("corp 500")),
        fetch_alliance=lambda all_id: (_ for _ in ()).throw(RuntimeError("alliance 500")),
        fetch_location=lambda cid, tok: {"solar_system_id": 30000142},  # system-only
        fetch_ship=lambda cid, tok: (_ for _ in ()).throw(RuntimeError("ship 500")),
        fetch_online=lambda cid, tok: (_ for _ in ()).throw(RuntimeError("online 500")),
    )

    summary = ue.sync_character(db, char)
    assert summary["errors"] == []
    assert summary["counts"]["affiliation"] == 1
    assert summary["counts"]["location"] == 1
    # corp id still set, but the name fetch failed silently
    assert char.corporation_id == 1000 and char.corporation_name is None
    assert char.alliance_name is None
    # system-only location → no station/structure id
    assert char.location_id is None and char.location_type == "system"
    assert char.ship_type_id is None and char.online is None


def test_sync_character_skips_bad_mining_rows(monkeypatch, db):
    # rows with an unparseable date or missing type_id are filtered out
    char = _seed_char(db)
    _patch_token(monkeypatch)
    _patch_all_esi(
        monkeypatch,
        fetch_mining=lambda cid, tok: [
            {"date": "not-a-date", "type_id": 1230, "solar_system_id": 30000142, "quantity": 1},
            {"date": "2026-02-02", "type_id": None, "solar_system_id": 30000142, "quantity": 1},
            {"date": "2026-02-03", "type_id": 1230, "solar_system_id": 30000142, "quantity": 9},
        ],
    )
    summary = ue.sync_character(db, char)
    assert summary["counts"]["mining"] == 1  # only the one valid row
    assert db.query(EsiMiningLedger).count() == 1


def test_sync_character_token_failure_raises(monkeypatch, db):
    char = _seed_char(db)

    def boom(db_, c):
        raise RuntimeError("refresh failed")
    monkeypatch.setattr(ue.esi, "valid_access_token", boom)
    with pytest.raises(RuntimeError, match="refresh failed"):
        ue.sync_character(db, char)


# ── sync_all_active (job entry point) ─────────────────────────────────────────

def test_sync_all_active(monkeypatch, db):
    _seed_char(db, scopes="")  # minimal scopes keeps it fast
    monkeypatch.setattr(ue, "SessionLocal", lambda: db)
    _patch_token(monkeypatch)
    _patch_all_esi(monkeypatch)

    summary = ue.sync_all_active()
    assert summary["characters"] == 1
    assert len(summary["results"]) == 1
    assert summary["errors"] == []
    assert "seconds" in summary["results"][0]


def test_sync_all_active_no_characters(monkeypatch, db):
    monkeypatch.setattr(ue, "SessionLocal", lambda: db)
    summary = ue.sync_all_active()
    assert summary == {"characters": 0, "results": [], "errors": []}


def test_sync_all_active_inactive_excluded(monkeypatch, db):
    _seed_char(db, scopes="")
    db.add(LinkedCharacter(id=2, user_id=1, character_id=90000002, character_name="Inactive",
                           scopes="", is_active=False, status="active"))
    db.add(LinkedCharacter(id=3, user_id=1, character_id=90000003, character_name="Expired",
                           scopes="", is_active=True, status="token_expired"))
    db.commit()
    monkeypatch.setattr(ue, "SessionLocal", lambda: db)
    _patch_token(monkeypatch)
    _patch_all_esi(monkeypatch)

    summary = ue.sync_all_active()
    # only the active+active character is synced
    assert summary["characters"] == 1


def test_sync_all_active_captures_sync_error(monkeypatch, db):
    _seed_char(db, scopes="")
    monkeypatch.setattr(ue, "SessionLocal", lambda: db)

    def boom(db_, char):
        raise RuntimeError("sync exploded")
    monkeypatch.setattr(ue, "sync_character", boom)

    summary = ue.sync_all_active()
    assert summary["characters"] == 1
    assert any("sync exploded" in e for e in summary["errors"])
