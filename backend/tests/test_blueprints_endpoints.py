"""
Blueprint CRUD + paste-import endpoints (app/api/blueprints_router.py), exercised
the project's no-HTTP way: the async route functions are called directly with
seeded in-memory SQLite sessions.

``create_blueprint`` / ``import_blueprints`` open their own SDE session via
``EveSessionLocal()`` (not an injected dep), so we monkeypatch that factory to
hand back the seeded in-memory SDE session — its ``close`` is neutralised so the
router's ``finally: eve_db.close()`` doesn't tear the fixture down mid-test. The
real ``eve_repo`` helpers (product_for_blueprint / types_by_name) then run against
seeded ``eve_activity_products`` + ``eve_types`` rows, so ``_resolve_product`` is
covered for real (product found → 201, not-a-blueprint → 400).
"""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import blueprints_router as br
from app.api.blueprints_router import BlueprintIn, BlueprintUpdate, ImportRequest, ImportRow
from app.core.database import Base, UserDB, Organisation, OrganisationMember, Blueprint
from app.core.database_eve import EveBase, EveType, EveActivityProduct

USER = SimpleNamespace(id=1)
SEED_HASH = "x"  # placeholder password hash for seeded test users (not a real credential)

# Blueprint type 1000 (manufacturing, activity 1) makes product 587.
BP_TYPE_ID = 1000
PRODUCT_TYPE_ID = 587
NOT_A_BP_TYPE_ID = 9999  # no eve_activity_products row → _resolve_product 400


def run(coro):
    return asyncio.run(coro)


def _mem_db(base):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


@pytest.fixture
def app_db():
    session, engine = _mem_db(Base)
    session.add(UserDB(id=1, username="u", email="u@example.com", hashed_password=SEED_HASH))
    session.commit()
    yield session
    session.close(); engine.dispose()


@pytest.fixture
def eve_db():
    session, engine = _mem_db(EveBase)
    session.add_all([
        EveType(type_id=BP_TYPE_ID, type_name="Rifter Blueprint", group_id=105, published=True),
        EveType(type_id=PRODUCT_TYPE_ID, type_name="Rifter", group_id=25, published=True),
        EveActivityProduct(type_id=BP_TYPE_ID, activity_id=1,
                           product_type_id=PRODUCT_TYPE_ID, quantity=1),
    ])
    session.commit()
    yield session
    session.close(); engine.dispose()


@pytest.fixture(autouse=True)
def _wire_eve_session(eve_db, monkeypatch):
    """``create_blueprint``/``import_blueprints`` call ``EveSessionLocal()`` themselves;
    hand them the seeded fixture session with a no-op ``close`` so the router's
    ``finally: eve_db.close()`` doesn't dispose it before the test ends."""
    monkeypatch.setattr(eve_db, "close", lambda: None)
    monkeypatch.setattr(br, "EveSessionLocal", lambda: eve_db)


# ── create ───────────────────────────────────────────────────────────────────

def test_create_blueprint_resolves_product(app_db):
    out = run(br.create_blueprint(
        body=BlueprintIn(blueprint_type_id=BP_TYPE_ID, name="Rifter BPO", me=10, te=20),
        current_user=USER, db=app_db))
    assert out.product_type_id == PRODUCT_TYPE_ID
    assert out.user_id == 1
    assert out.is_bpo is True
    assert out.runs is None          # BPO → runs forced to None
    assert out.me == 10 and out.te == 20
    assert out.id


def test_create_bpc_keeps_runs(app_db):
    out = run(br.create_blueprint(
        body=BlueprintIn(blueprint_type_id=BP_TYPE_ID, name="Rifter BPC",
                         is_bpo=False, runs=50, cost=1234.0),
        current_user=USER, db=app_db))
    assert out.is_bpo is False
    assert out.runs == 50            # BPC → runs preserved
    assert out.cost == pytest.approx(1234.0)


def test_create_blueprint_not_a_blueprint_400(app_db):
    with pytest.raises(HTTPException) as ei:
        run(br.create_blueprint(
            body=BlueprintIn(blueprint_type_id=NOT_A_BP_TYPE_ID, name="Junk"),
            current_user=USER, db=app_db))
    assert ei.value.status_code == 400


# ── list ───────────────────────────────────────────────────────────────────--

def _make_bp(app_db, **kw):
    defaults = dict(user_id=1, blueprint_type_id=BP_TYPE_ID, product_type_id=PRODUCT_TYPE_ID,
                    name="BP", is_bpo=True, me=0, te=0, quantity=1)
    defaults.update(kw)
    bp = Blueprint(**defaults)
    app_db.add(bp); app_db.commit(); app_db.refresh(bp)
    return bp


def test_list_returns_own_and_org_blueprints(app_db):
    # owned org + a joined org, each with one blueprint, plus a personal one
    app_db.add(Organisation(id=10, name="MyCorp", owner_id=1))
    app_db.add(Organisation(id=20, name="JoinedCorp", owner_id=2))
    app_db.add(OrganisationMember(org_id=20, user_id=1, role="JUNIOR"))
    app_db.commit()
    _make_bp(app_db, name="Personal")
    _make_bp(app_db, name="Owned", organisation_id=10)
    _make_bp(app_db, name="Joined", organisation_id=20)
    # a blueprint that belongs to neither the user nor an accessible org → excluded
    _make_bp(app_db, user_id=2, name="Foreign", organisation_id=99)

    rows = run(br.list_blueprints(current_user=USER, db=app_db))
    names = {r.name for r in rows}
    assert names == {"Personal", "Owned", "Joined"}
    # ordered by name
    assert [r.name for r in rows] == sorted(names)


def test_list_empty_when_no_orgs(app_db):
    # user owns/joined nothing; only a personal blueprint is visible
    _make_bp(app_db, name="Solo")
    rows = run(br.list_blueprints(current_user=USER, db=app_db))
    assert [r.name for r in rows] == ["Solo"]


def test_list_filters_by_org_and_product(app_db):
    app_db.add(Organisation(id=10, name="MyCorp", owner_id=1)); app_db.commit()
    _make_bp(app_db, name="A", organisation_id=10, product_type_id=587)
    _make_bp(app_db, name="B", organisation_id=10, product_type_id=999)
    _make_bp(app_db, name="C", product_type_id=587)  # personal, no org

    by_org = run(br.list_blueprints(organisation_id=10, current_user=USER, db=app_db))
    assert {r.name for r in by_org} == {"A", "B"}

    by_prod = run(br.list_blueprints(product_type_id=587, current_user=USER, db=app_db))
    assert {r.name for r in by_prod} == {"A", "C"}


# ── update ───────────────────────────────────────────────────────────────────

def test_update_blueprint(app_db):
    bp = _make_bp(app_db, name="Old", me=0, is_bpo=False, runs=10)
    out = run(br.update_blueprint(bp_id=bp.id,
                                  body=BlueprintUpdate(name="New", me=8, note="hi"),
                                  current_user=USER, db=app_db))
    assert out.name == "New" and out.me == 8 and out.note == "hi"
    assert out.updated_at is not None
    assert out.runs == 10  # still a BPC, runs untouched


def test_update_to_bpo_clears_runs(app_db):
    bp = _make_bp(app_db, name="BPC", is_bpo=False, runs=10)
    out = run(br.update_blueprint(bp_id=bp.id, body=BlueprintUpdate(is_bpo=True),
                                  current_user=USER, db=app_db))
    assert out.is_bpo is True
    assert out.runs is None  # flipping to BPO nulls runs


def test_update_missing_404(app_db):
    with pytest.raises(HTTPException) as ei:
        run(br.update_blueprint(bp_id=12345, body=BlueprintUpdate(name="x"),
                                current_user=USER, db=app_db))
    assert ei.value.status_code == 404


def test_update_other_users_blueprint_404(app_db):
    bp = _make_bp(app_db, user_id=2, name="NotMine")
    with pytest.raises(HTTPException) as ei:
        run(br.update_blueprint(bp_id=bp.id, body=BlueprintUpdate(name="x"),
                                current_user=USER, db=app_db))
    assert ei.value.status_code == 404


# ── delete ───────────────────────────────────────────────────────────────────

def test_delete_blueprint(app_db):
    bp = _make_bp(app_db, name="Doomed")
    assert run(br.delete_blueprint(bp_id=bp.id, current_user=USER, db=app_db)) is None
    assert app_db.query(Blueprint).filter(Blueprint.id == bp.id).first() is None


def test_delete_missing_404(app_db):
    with pytest.raises(HTTPException) as ei:
        run(br.delete_blueprint(bp_id=999, current_user=USER, db=app_db))
    assert ei.value.status_code == 404


# ── import ───────────────────────────────────────────────────────────────────

def test_import_blueprints_resolves_and_skips_unknown(app_db):
    body = ImportRequest(rows=[
        ImportRow(name="Rifter Blueprint", is_bpo=True, me=5, te=4),
        ImportRow(name="Rifter Blueprint", is_bpo=False, runs=7, me=2, te=1),
        ImportRow(name="Totally Unknown Thing"),  # not in eve_types → unresolved
    ])
    out = run(br.import_blueprints(body=body, current_user=USER, db=app_db))

    assert out["created_count"] == 2
    assert out["created"] == ["Rifter Blueprint", "Rifter Blueprint"]
    assert out["unresolved"] == ["Totally Unknown Thing"]

    rows = app_db.query(Blueprint).order_by(Blueprint.id).all()
    assert len(rows) == 2
    assert all(r.blueprint_type_id == BP_TYPE_ID for r in rows)
    assert all(r.product_type_id == PRODUCT_TYPE_ID for r in rows)
    assert rows[0].is_bpo is True and rows[0].runs is None      # BPO drops runs
    assert rows[1].is_bpo is False and rows[1].runs == 7        # BPC keeps runs


def test_import_blueprints_all_unresolved(app_db):
    body = ImportRequest(rows=[ImportRow(name="Nope"), ImportRow(name="   ")])
    out = run(br.import_blueprints(body=body, current_user=USER, db=app_db))
    assert out["created_count"] == 0
    assert out["created"] == []
    assert sorted(out["unresolved"]) == ["   ", "Nope"]
    assert app_db.query(Blueprint).count() == 0
