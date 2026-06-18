"""
Facilities endpoints (player-owned structures): facility CRUD scoped to the
owning user, plus org-member visibility in the list route. Driven the project's
no-HTTP way — the async route functions are called directly against an in-memory
SQLite session with a seeded user/org; no network is touched.
"""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import facilities_router as fr
from app.api.facilities_router import FacilityCreate, FacilityUpdate, RigIn
from app.core.database import Base, UserDB, Organisation, OrganisationMember
from app.core.schemas import FacilityType, OrganisationType

USER = SimpleNamespace(id=1)
OTHER = SimpleNamespace(id=999)
SEED_HASH = "x"  # placeholder password hash for seeded test users (not a real credential)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        UserDB(id=1, username="u", email="u@example.com", hashed_password=SEED_HASH),
        UserDB(id=999, username="other", email="o@example.com", hashed_password=SEED_HASH),
    ])
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _seed_org(db, owner_id=1):
    org = Organisation(name="Org", owner_id=owner_id, org_type=OrganisationType.PERSONAL.value)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _create(db, current_user=USER, **kw):
    body = FacilityCreate(**{
        "name": "Raitaru-1",
        "facility_type": FacilityType.RAITARU,
        **kw,
    })
    return run(fr.create_facility(body=body, current_user=current_user, db=db))


# ── create ───────────────────────────────────────────────────────────────────

def test_create_facility_persists_all_fields(db):
    out = _create(
        db,
        name="Sotiyo-X",
        facility_type=FacilityType.SOTIYO,
        tax=1.5,
        cost_bonus=2.0,
        system_name="Jita",
        system_cost_index=0.05,
        rig1=RigIn(type_id=37180, name="T2 Rig"),
        rig2=RigIn(type_id=None, name=None),
    )
    assert out.id is not None
    assert out.user_id == 1
    assert out.name == "Sotiyo-X"
    assert out.facility_type == FacilityType.SOTIYO
    assert out.tax == pytest.approx(1.5) and out.cost_bonus == pytest.approx(2.0)
    assert out.system_name == "Jita" and out.system_cost_index == pytest.approx(0.05)
    assert out.rig1.type_id == 37180 and out.rig1.name == "T2 Rig"
    assert out.rig2.type_id is None
    assert out.rig3.type_id is None  # rig3 omitted entirely
    assert out.created_at is not None


def test_create_facility_with_organisation(db):
    org = _seed_org(db)
    out = _create(db, organisation_id=org.id)
    assert out.organisation_id == org.id


# ── list ───────────────────────────────────────────────────────────────────

def test_list_returns_own_facilities(db):
    _create(db, name="A", facility_type=FacilityType.RAITARU)
    _create(db, name="B", facility_type=FacilityType.AZBEL)
    listed = run(fr.list_facilities(current_user=USER, db=db))
    # ordered by name
    assert [f.name for f in listed] == ["A", "B"]


def test_list_excludes_other_users_facilities(db):
    _create(db, current_user=OTHER, name="Theirs")
    listed = run(fr.list_facilities(current_user=USER, db=db))
    assert listed == []


def test_list_filter_by_facility_type(db):
    _create(db, name="A", facility_type=FacilityType.RAITARU)
    _create(db, name="B", facility_type=FacilityType.AZBEL)
    listed = run(fr.list_facilities(facility_type=FacilityType.AZBEL, current_user=USER, db=db))
    assert [f.name for f in listed] == ["B"]


def test_list_filter_by_organisation_id(db):
    org = _seed_org(db)
    _create(db, name="InOrg", organisation_id=org.id)
    _create(db, name="NoOrg")
    listed = run(fr.list_facilities(organisation_id=org.id, current_user=USER, db=db))
    assert [f.name for f in listed] == ["InOrg"]


def test_list_includes_member_org_facilities(db):
    # OTHER owns an org and a facility in it; USER is an accepted member → visible.
    org = _seed_org(db, owner_id=OTHER.id)
    _create(db, current_user=OTHER, name="OrgFac", organisation_id=org.id)
    db.add(OrganisationMember(org_id=org.id, user_id=USER.id, role="JUNIOR"))
    db.commit()
    listed = run(fr.list_facilities(current_user=USER, db=db))
    assert [f.name for f in listed] == ["OrgFac"]


# ── get ───────────────────────────────────────────────────────────────────

def test_get_facility_success(db):
    created = _create(db)
    got = run(fr.get_facility(facility_id=created.id, current_user=USER, db=db))
    assert got.id == created.id and got.name == created.name


def test_get_facility_not_found(db):
    with pytest.raises(HTTPException) as exc:
        run(fr.get_facility(facility_id=12345, current_user=USER, db=db))
    assert exc.value.status_code == 404


def test_get_facility_forbidden_for_other_user(db):
    created = _create(db, current_user=OTHER)
    # USER cannot see OTHER's facility → scoped 404
    with pytest.raises(HTTPException) as exc:
        run(fr.get_facility(facility_id=created.id, current_user=USER, db=db))
    assert exc.value.status_code == 404


# ── update ───────────────────────────────────────────────────────────────────

def test_update_facility_changes_fields(db):
    org = _seed_org(db)
    created = _create(db)
    out = run(fr.update_facility(
        facility_id=created.id,
        body=FacilityUpdate(
            name="Renamed",
            facility_type=FacilityType.TATARA,
            organisation_id=org.id,
            tax=9.0,
            cost_bonus=3.0,
            system_name="Amarr",
            system_cost_index=0.07,
            rig1=RigIn(type_id=1, name="R1"),
            rig2=RigIn(type_id=2, name="R2"),
            rig3=RigIn(type_id=3, name="R3"),
        ),
        current_user=USER, db=db,
    ))
    assert out.name == "Renamed"
    assert out.facility_type == FacilityType.TATARA
    assert out.organisation_id == org.id
    assert out.tax == pytest.approx(9.0) and out.cost_bonus == pytest.approx(3.0)
    assert out.system_name == "Amarr" and out.system_cost_index == pytest.approx(0.07)
    assert out.rig1.name == "R1" and out.rig2.name == "R2" and out.rig3.name == "R3"
    assert out.updated_at is not None


def test_update_facility_partial_leaves_other_fields(db):
    created = _create(db, name="Orig", tax=1.0)
    out = run(fr.update_facility(
        facility_id=created.id,
        body=FacilityUpdate(name="OnlyName"),
        current_user=USER, db=db,
    ))
    assert out.name == "OnlyName"
    assert out.tax == pytest.approx(1.0)  # untouched


def test_update_facility_not_found(db):
    with pytest.raises(HTTPException) as exc:
        run(fr.update_facility(facility_id=999999, body=FacilityUpdate(name="x"),
                               current_user=USER, db=db))
    assert exc.value.status_code == 404


# ── delete ───────────────────────────────────────────────────────────────────

def test_delete_facility_success(db):
    created = _create(db)
    result = run(fr.delete_facility(facility_id=created.id, current_user=USER, db=db))
    assert result is None
    # gone afterwards
    with pytest.raises(HTTPException):
        run(fr.get_facility(facility_id=created.id, current_user=USER, db=db))


def test_delete_facility_not_found(db):
    with pytest.raises(HTTPException) as exc:
        run(fr.delete_facility(facility_id=424242, current_user=USER, db=db))
    assert exc.value.status_code == 404
