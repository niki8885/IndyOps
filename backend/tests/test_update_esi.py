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
    EsiBlueprintCopy, EsiMarketOrder, BankLedgerEntry, EsiWalletEntry, CharacterWealthSnapshot,
)
from app.tasks import update_esi as ue

CID = 90000001

_ESI_TABLES = [
    LinkedCharacter, EsiWalletTransaction, EsiSkill, EsiAsset, EsiContract,
    EsiIndustryJob, EsiStanding, EsiStructure, EsiImplant, EsiMiningLedger,
    EsiBlueprintCopy, EsiMarketOrder, BankLedgerEntry, EsiWalletEntry, CharacterWealthSnapshot,
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
    # the module-level price + bank-corp caches leak across tests otherwise
    ue._price_cache["prices"] = None
    ue._price_cache["ts"] = None
    ue._bank_corp_cache["id"] = None
    yield
    ue._price_cache["prices"] = None
    ue._price_cache["ts"] = None
    ue._bank_corp_cache["id"] = None


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
        "fetch_market_orders": lambda cid, tok: [],
        "fetch_wallet_journal": lambda cid, tok: [],
        "resolve_ids": lambda names: {},   # bank corp can't be resolved → bank step no-ops
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


# ── _job_notify (industry-job completion notifications) ────────────────────────

def test_job_notify_emits_once_and_self_dismisses():
    from app.core.database import AgendaNotification
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        LinkedCharacter.__table__, EsiIndustryJob.__table__, AgendaNotification.__table__])
    db = sessionmaker(bind=engine)()
    try:
        char = LinkedCharacter(user_id=42, character_id=CID, character_name="Maker", scopes="")
        row = EsiIndustryJob(character_id=CID, job_id=11, blueprint_type_id=1, product_type_id=2,
                             runs=10, status="ready", notified_ready=False)
        db.add_all([char, row])
        db.commit()
        now = datetime.datetime(2026, 6, 27, 12, 0, 0)

        # status 'ready' → one notification, latch set, tagged with the job source_key
        ue._job_notify(db, char, row, "Widget", "ready", now)
        db.commit()
        notes = db.query(AgendaNotification).all()
        assert len(notes) == 1 and row.notified_ready is True
        assert notes[0].source_key == "job_ready:11" and "Widget" in notes[0].body

        # still 'ready' next sync → no duplicate (latched)
        ue._job_notify(db, char, row, "Widget", "ready", now)
        db.commit()
        assert db.query(AgendaNotification).count() == 1

        # collected ('delivered') → notification withdrawn, latch cleared
        ue._job_notify(db, char, row, "Widget", "delivered", now)
        db.commit()
        assert db.query(AgendaNotification).count() == 0 and row.notified_ready is False
    finally:
        db.close()
        engine.dispose()


# ── Corporation-level sync (Phase B) ───────────────────────────────────────────

def test_best_corp_grantor_role_and_scope():
    wallet_sc = ue._CORP_WALLET_SCOPE
    has_role = LinkedCharacter(scopes=wallet_sc, corp_roles=["Accountant"])
    no_role = LinkedCharacter(scopes=wallet_sc, corp_roles=["Member"])
    no_scope = LinkedCharacter(scopes="", corp_roles=["Director"])
    assert ue._best_corp_grantor([no_role, has_role], ue._ROLE_ACCOUNTANT, wallet_sc) is has_role
    assert ue._best_corp_grantor([no_role, no_scope], ue._ROLE_ACCOUNTANT, wallet_sc) is None
    assert ue._best_corp_grantor([no_role], None, wallet_sc) is no_role   # scope-only (membership)


def _corp_db():
    from app.core.database import (
        EsiCorpWallet, EsiCorpIndustryJob, EsiCorpMember,
        EsiCorpAsset, EsiCorpDivision, EsiCorpContract, EsiCorpContractItem,
    )
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        LinkedCharacter.__table__, EsiCorpWallet.__table__,
        EsiCorpIndustryJob.__table__, EsiCorpMember.__table__,
        EsiCorpAsset.__table__, EsiCorpDivision.__table__,
        EsiCorpContract.__table__, EsiCorpContractItem.__table__])
    return sessionmaker(bind=engine)(), engine


def test_sync_corporations_pulls_real_corp_data(monkeypatch):
    from app.core.database import EsiCorpWallet, EsiCorpIndustryJob, EsiCorpMember
    db, engine = _corp_db()
    try:
        director = LinkedCharacter(
            user_id=1, character_id=CID, character_name="Boss", corporation_id=2000,
            is_active=True, status="active", corp_roles=["Director"],
            scopes=" ".join([ue._CORP_WALLET_SCOPE, ue._CORP_JOBS_SCOPE, ue._CORP_MEMBERS_SCOPE]))
        grunt = LinkedCharacter(
            user_id=2, character_id=CID + 1, character_name="Grunt", corporation_id=2000,
            is_active=True, status="active", corp_roles=["Member"], scopes="")
        db.add_all([director, grunt])
        db.commit()

        monkeypatch.setattr(ue.esi, "valid_access_token", lambda db, char: "tok")
        monkeypatch.setattr(ue.esi, "fetch_corp_wallets",
                            lambda corp, tok: [{"division": 1, "balance": 1000.0}, {"division": 2, "balance": 500.0}])
        monkeypatch.setattr(ue.esi, "fetch_corp_industry_jobs",
                            lambda corp, tok: [{"job_id": 9001, "installer_id": CID, "activity_id": 1,
                                                "product_type_id": 587, "runs": 5, "status": "active",
                                                "end_date": "2026-07-01T00:00:00Z", "cost": 12.5}])
        monkeypatch.setattr(ue.esi, "fetch_corp_members", lambda corp, tok: [CID, CID + 1, CID + 2])

        out = ue.sync_corporations(db)
        assert out["corporations"] == 1

        wallets = db.query(EsiCorpWallet).filter_by(corporation_id=2000).all()
        assert {w.division for w in wallets} == {1, 2}
        assert sum(w.balance for w in wallets) == 1500.0 and wallets[0].synced_by == CID

        jobs = db.query(EsiCorpIndustryJob).filter_by(corporation_id=2000).all()
        assert len(jobs) == 1 and jobs[0].job_id == 9001 and jobs[0].runs == 5

        members = db.query(EsiCorpMember).filter_by(corporation_id=2000).all()
        assert {m.character_id for m in members} == {CID, CID + 1, CID + 2}
        names = {m.character_id: m.character_name for m in members}
        assert names[CID] == "Boss" and names[CID + 2] is None   # 3rd member unknown → no name

        # prune: a later sync with no jobs clears the corp's jobs
        monkeypatch.setattr(ue.esi, "fetch_corp_industry_jobs", lambda corp, tok: [])
        ue.sync_corporations(db)
        assert db.query(EsiCorpIndustryJob).filter_by(corporation_id=2000).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_sync_corporations_pulls_assets_contracts_divisions(monkeypatch):
    from app.core.database import (
        EsiCorpAsset, EsiCorpDivision, EsiCorpContract, EsiCorpContractItem,
    )
    db, engine = _corp_db()
    try:
        director = LinkedCharacter(
            user_id=1, character_id=CID, character_name="Boss", corporation_id=2000,
            is_active=True, status="active", corp_roles=["Director"],
            scopes=" ".join([ue._CORP_ASSETS_SCOPE, ue._CORP_DIVISIONS_SCOPE, ue._CORP_CONTRACTS_SCOPE]))
        db.add(director)
        db.commit()

        monkeypatch.setattr(ue.esi, "valid_access_token", lambda db, char: "tok")
        monkeypatch.setattr(ue.esi, "fetch_corp_assets",
                            lambda corp, tok: [{"item_id": 1, "type_id": 34, "quantity": 100,
                                                "location_id": 60003760, "location_flag": "CorpSAG1",
                                                "location_type": "station"}])
        monkeypatch.setattr(ue.esi, "fetch_corp_divisions",
                            lambda corp, tok: {"hangar": [{"division": 1, "name": "Minerals"}],
                                               "wallet": [{"division": 1, "name": "Master"}]})
        monkeypatch.setattr(ue.esi, "fetch_corp_contracts",
                            lambda corp, tok: [{"contract_id": 7001, "type": "item_exchange",
                                                "status": "outstanding", "issuer_id": CID,
                                                "date_issued": "2026-06-01T00:00:00Z", "price": 1000.0}])
        monkeypatch.setattr(ue.esi, "fetch_corp_contract_items",
                            lambda corp, cid, tok: [{"record_id": 1, "type_id": 34, "quantity": 50,
                                                     "is_included": True}])

        out = ue.sync_corporations(db)
        assert out["corporations"] == 1

        assets = db.query(EsiCorpAsset).filter_by(corporation_id=2000).all()
        assert len(assets) == 1 and assets[0].location_flag == "CorpSAG1"
        divs = {(d.kind, d.division): d.name for d in
                db.query(EsiCorpDivision).filter_by(corporation_id=2000).all()}
        assert divs[("hangar", 1)] == "Minerals" and divs[("wallet", 1)] == "Master"
        contracts = db.query(EsiCorpContract).filter_by(corporation_id=2000).all()
        assert len(contracts) == 1 and contracts[0].contract_id == 7001
        items = db.query(EsiCorpContractItem).filter_by(corporation_id=2000, contract_id=7001).all()
        assert len(items) == 1 and items[0].quantity == 50

        # a second sync must NOT re-fetch already-itemized contracts (immutable contents)
        monkeypatch.setattr(ue.esi, "fetch_corp_contract_items",
                            lambda corp, cid, tok: (_ for _ in ()).throw(AssertionError("re-fetched")))
        ue.sync_corporations(db)
        assert db.query(EsiCorpContractItem).filter_by(corporation_id=2000).count() == 1

        # prune: a later sync with no contracts clears them + their items
        monkeypatch.setattr(ue.esi, "fetch_corp_contracts", lambda corp, tok: [])
        ue.sync_corporations(db)
        assert db.query(EsiCorpContract).filter_by(corporation_id=2000).count() == 0
        assert db.query(EsiCorpContractItem).filter_by(corporation_id=2000).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_sync_corporations_skips_corp_without_roles(monkeypatch):
    from app.core.database import EsiCorpWallet
    db, engine = _corp_db()
    try:
        member = LinkedCharacter(
            user_id=1, character_id=CID, character_name="Nobody", corporation_id=3000,
            is_active=True, status="active", corp_roles=["Member"],
            scopes=" ".join([ue._CORP_WALLET_SCOPE, ue._CORP_JOBS_SCOPE]))
        db.add(member)
        db.commit()
        monkeypatch.setattr(ue.esi, "valid_access_token", lambda db, char: "tok")
        monkeypatch.setattr(ue.esi, "fetch_corp_wallets",
                            lambda corp, tok: (_ for _ in ()).throw(AssertionError("must not be called")))
        out = ue.sync_corporations(db)
        assert out["corporations"] == 1 and db.query(EsiCorpWallet).count() == 0
    finally:
        db.close()
        engine.dispose()


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
    # market orders are scope-gated (not granted here) and the bank corp can't be
    # resolved in the test, so both new steps no-op without erroring
    assert counts["market_orders"] == 0
    assert counts["bank_donations"] == 0

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


# ── sync_character — market orders + bank donations ───────────────────────────

def test_sync_character_market_orders(monkeypatch, db):
    char = _seed_char(db, scopes=ue._MARKET_ORDERS_SCOPE)
    _patch_token(monkeypatch)
    _patch_all_esi(monkeypatch, fetch_market_orders=lambda cid, tok: [
        {"order_id": 1, "type_id": 34, "region_id": 10000002, "location_id": 60003760,
         "is_buy_order": False, "price": 5.5, "volume_total": 100, "volume_remain": 40,
         "min_volume": 1, "range": "region", "duration": 90, "issued": "2026-06-20T12:00:00Z"},
    ])
    summary = ue.sync_character(db, char)
    assert summary["counts"]["market_orders"] == 1
    o = db.query(EsiMarketOrder).one()
    assert o.order_id == 1 and o.is_buy_order is False and o.price == pytest.approx(5.5)
    assert o.volume_remain == 40 and o.region_id == 10000002


def test_sync_character_bank_donation_credits_and_is_idempotent(monkeypatch, db):
    char = _seed_char(db, scopes="")
    _patch_token(monkeypatch)
    _patch_all_esi(
        monkeypatch,
        resolve_ids=lambda names: {"corporations": [{"id": 98000001, "name": "Miners and Merchants Bank"}]},
        fetch_wallet_journal=lambda cid, tok: [
            {"id": 777, "ref_type": "player_donation", "second_party_id": 98000001,
             "amount": -1000.11, "date": "2026-06-24T15:19:00Z", "reason": "deposit"},
            {"id": 778, "ref_type": "player_donation", "second_party_id": 12345,   # different corp
             "amount": -500.0, "date": "2026-06-24T15:20:00Z"},
            {"id": 779, "ref_type": "bounty_prizes", "second_party_id": 98000001,  # not a donation
             "amount": -10.0, "date": "2026-06-24T15:21:00Z"},
            {"id": 780, "ref_type": "player_donation", "second_party_id": 98000001,  # incoming, not a deposit
             "amount": 99.0, "date": "2026-06-24T15:22:00Z"},
        ],
    )
    summary = ue.sync_character(db, char)
    assert summary["counts"]["bank_donations"] == 1
    entry = db.query(BankLedgerEntry).one()
    assert entry.ref_id == 777 and entry.amount_penny == 100011   # 1,000.11 ISK
    assert entry.user_id == 1 and entry.character_id == CID

    # a second sync must not double-credit the same journal entry
    ue.sync_character(db, char)
    assert db.query(BankLedgerEntry).count() == 1


def test_sync_character_captures_income_and_is_idempotent(monkeypatch, db):
    char = _seed_char(db, scopes="")
    _patch_token(monkeypatch)
    _patch_all_esi(
        monkeypatch,
        fetch_wallet_journal=lambda cid, tok: [
            {"id": 1, "ref_type": "agent_mission_reward", "amount": 500000.0,
             "first_party_id": 3019582, "date": "2026-06-24T15:19:00Z"},
            {"id": 2, "ref_type": "agent_mission_time_bonus_reward", "amount": 250000.0,
             "first_party_id": 3019582, "date": "2026-06-24T15:19:05Z"},
            {"id": 3, "ref_type": "bounty_prizes", "amount": 1_200_000.0,
             "date": "2026-06-24T16:00:00Z"},
            {"id": 4, "ref_type": "ess_escrow_transfer", "amount": 800_000.0,
             "date": "2026-06-24T16:30:00Z"},
            {"id": 5, "ref_type": "market_transaction", "amount": -42.0,   # ignored ref_type
             "date": "2026-06-24T17:00:00Z"},
        ],
    )
    summary = ue.sync_character(db, char)
    assert summary["counts"]["wallet_income"] == 4   # the 5th (market_transaction) is ignored

    rows = db.query(EsiWalletEntry).all()
    assert {r.ref_type for r in rows} == set(ue._INCOME_REF_TYPES)
    mission = next(r for r in rows if r.ref_type == "agent_mission_reward")
    assert mission.amount == pytest.approx(500000.0) and mission.first_party_id == 3019582
    assert mission.user_id == 1 and mission.character_id == CID

    # a second sync must not duplicate the same journal entries
    ue.sync_character(db, char)
    assert db.query(EsiWalletEntry).count() == 4


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
    assert summary["characters"] == 0 and summary["results"] == [] and summary["errors"] == []
    assert summary["corporations"]["corporations"] == 0   # corp pass ran, found no corps


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
