"""
Projects CRUD endpoints (projects_router): create / list / get / update / delete.
Driven against in-memory SQLite the project's no-HTTP way — the async endpoint
functions are called directly with seeded sessions, no network is touched.

Access control: the org owner gets an implicit "OWNER" role (write access), so a
project owned by user 1 satisfies both read and write checks. Other users are not
members and hit 403; missing rows hit 404.
"""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import projects_router as pr
from app.api.projects_router import ProjectCreate, ProjectUpdate
from app.core.database import Base, UserDB, Organisation, Employee, Projects
from app.core.schemas import ProjectsType, ProjectsStatus, ProjectPriority, EmployeeType

USER = SimpleNamespace(id=1)
OTHER = SimpleNamespace(id=2)
SEED_HASH = "x"  # placeholder password hash for seeded test users (not a real credential)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    # two users; org is owned by user 1
    session.add(UserDB(id=1, username="u1", email="u1@example.com", hashed_password=SEED_HASH))
    session.add(UserDB(id=2, username="u2", email="u2@example.com", hashed_password=SEED_HASH))
    session.commit()
    yield session
    session.close(); engine.dispose()


def _seed_org(db, org_id=1, owner_id=1):
    org = Organisation(id=org_id, name=f"Org{org_id}", owner_id=owner_id,
                       org_type="Personal")
    db.add(org)
    db.commit()
    return org


def _seed_emp(db, emp_id=1, user_id=1, org_id=1, name=None):
    emp = Employee(id=emp_id, name=name or f"Emp{emp_id}", user_id=user_id,
                   organisation_id=org_id, status=EmployeeType.OWNER)
    db.add(emp)
    db.commit()
    return emp


def _create_body(**kw):
    base = dict(name="Proj A", project_type=ProjectsType.INTERNAL, created_by=1)
    base.update(kw)
    return ProjectCreate(**base)


# ── create ────────────────────────────────────────────────────────────────────

def test_create_project_success(db):
    _seed_org(db); _seed_emp(db)
    out = run(pr.create_project(org_id=1, body=_create_body(note="hi", priority=ProjectPriority.HIGH),
                                current_user=USER, db=db))
    assert out.id is not None
    assert out.name == "Proj A"
    assert out.organisation_id == 1
    assert out.created_by == 1
    assert out.status == ProjectsStatus.ACTIVE
    assert out.priority == "high"
    assert out.note == "hi"


def test_create_project_with_supervisor(db):
    _seed_org(db); _seed_emp(db)
    _seed_emp(db, emp_id=2, user_id=1, org_id=1, name="Supervisor")
    out = run(pr.create_project(org_id=1, body=_create_body(supervised_by=2),
                                current_user=USER, db=db))
    assert out.supervised_by == 2


def test_create_project_org_not_found(db):
    with pytest.raises(HTTPException) as ei:
        run(pr.create_project(org_id=999, body=_create_body(), current_user=USER, db=db))
    assert ei.value.status_code == 404


def test_create_project_forbidden_non_member(db):
    _seed_org(db, owner_id=1)
    _seed_emp(db, emp_id=1, user_id=2, org_id=1)
    # OTHER (user 2) is not the owner and not a member → write access denied
    with pytest.raises(HTTPException) as ei:
        run(pr.create_project(org_id=1, body=_create_body(), current_user=OTHER, db=db))
    assert ei.value.status_code == 403


def test_create_project_creator_not_found(db):
    _seed_org(db)
    with pytest.raises(HTTPException) as ei:
        run(pr.create_project(org_id=1, body=_create_body(created_by=999),
                              current_user=USER, db=db))
    assert ei.value.status_code == 404


def test_create_project_creator_not_yours(db):
    _seed_org(db)
    # employee belongs to user 2, but current_user is user 1
    _seed_emp(db, emp_id=1, user_id=2, org_id=1)
    with pytest.raises(HTTPException) as ei:
        run(pr.create_project(org_id=1, body=_create_body(created_by=1),
                              current_user=USER, db=db))
    assert ei.value.status_code == 403


def test_create_project_supervisor_wrong_org(db):
    _seed_org(db, org_id=1)
    _seed_org(db, org_id=2, owner_id=1)
    _seed_emp(db, emp_id=1, user_id=1, org_id=1)
    _seed_emp(db, emp_id=2, user_id=1, org_id=2, name="OtherOrgEmp")  # in org 2
    with pytest.raises(HTTPException) as ei:
        run(pr.create_project(org_id=1, body=_create_body(supervised_by=2),
                              current_user=USER, db=db))
    assert ei.value.status_code == 400


def test_create_project_duplicate_name(db):
    _seed_org(db); _seed_emp(db)
    run(pr.create_project(org_id=1, body=_create_body(), current_user=USER, db=db))
    with pytest.raises(HTTPException) as ei:
        run(pr.create_project(org_id=1, body=_create_body(), current_user=USER, db=db))
    assert ei.value.status_code == 400


# ── list ────────────────────────────────────────────────────────────────────--

def test_list_projects_success_and_filters(db):
    _seed_org(db); _seed_emp(db)
    run(pr.create_project(org_id=1, body=_create_body(name="P1", project_type=ProjectsType.INTERNAL),
                          current_user=USER, db=db))
    run(pr.create_project(org_id=1, body=_create_body(name="P2", project_type=ProjectsType.SELL),
                          current_user=USER, db=db))

    all_rows = run(pr.list_projects(org_id=1, current_user=USER, db=db))
    assert {p.name for p in all_rows} == {"P1", "P2"}

    by_type = run(pr.list_projects(org_id=1, project_type=ProjectsType.SELL, current_user=USER, db=db))
    assert [p.name for p in by_type] == ["P2"]

    by_status = run(pr.list_projects(org_id=1, proj_status=ProjectsStatus.ACTIVE, current_user=USER, db=db))
    assert {p.name for p in by_status} == {"P1", "P2"}

    none_inactive = run(pr.list_projects(org_id=1, proj_status=ProjectsStatus.INACTIVE, current_user=USER, db=db))
    assert none_inactive == []


def test_list_projects_org_not_found(db):
    with pytest.raises(HTTPException) as ei:
        run(pr.list_projects(org_id=999, current_user=USER, db=db))
    assert ei.value.status_code == 404


def test_list_projects_forbidden_non_member(db):
    _seed_org(db, owner_id=1)
    with pytest.raises(HTTPException) as ei:
        run(pr.list_projects(org_id=1, current_user=OTHER, db=db))
    assert ei.value.status_code == 403


# ── get ──────────────────────────────────────────────────────────────────────

def test_get_project_success(db):
    _seed_org(db); _seed_emp(db)
    created = run(pr.create_project(org_id=1, body=_create_body(), current_user=USER, db=db))
    got = run(pr.get_project(org_id=1, project_id=created.id, current_user=USER, db=db))
    assert got.id == created.id and got.name == "Proj A"


def test_get_project_not_found(db):
    _seed_org(db)
    with pytest.raises(HTTPException) as ei:
        run(pr.get_project(org_id=1, project_id=12345, current_user=USER, db=db))
    assert ei.value.status_code == 404


def test_get_project_forbidden_non_member(db):
    _seed_org(db, owner_id=1)
    with pytest.raises(HTTPException) as ei:
        run(pr.get_project(org_id=1, project_id=1, current_user=OTHER, db=db))
    assert ei.value.status_code == 403


# ── update ─────────────────────────────────────────────────────────────────--

def test_update_project_success(db):
    _seed_org(db); _seed_emp(db)
    created = run(pr.create_project(org_id=1, body=_create_body(), current_user=USER, db=db))
    upd = run(pr.update_project(
        org_id=1, project_id=created.id,
        body=ProjectUpdate(name="Renamed", project_type=ProjectsType.OTHER,
                           status=ProjectsStatus.PAUSE, org_project_code="CODE-1",
                           note="updated", repeatable=True, closed=True,
                           priority=ProjectPriority.LOW),
        current_user=USER, db=db))
    assert upd.name == "Renamed"
    assert upd.project_type == ProjectsType.OTHER
    assert upd.status == ProjectsStatus.PAUSE
    assert upd.org_project_code == "CODE-1"
    assert upd.note == "updated"
    assert upd.repeatable is True
    assert upd.closed is True
    assert upd.priority == "low"
    assert upd.modified_at is not None


def test_update_project_supervisor(db):
    _seed_org(db); _seed_emp(db)
    _seed_emp(db, emp_id=2, user_id=1, org_id=1, name="Sup")
    created = run(pr.create_project(org_id=1, body=_create_body(), current_user=USER, db=db))
    upd = run(pr.update_project(org_id=1, project_id=created.id,
                                body=ProjectUpdate(supervised_by=2), current_user=USER, db=db))
    assert upd.supervised_by == 2


def test_update_project_supervisor_wrong_org(db):
    _seed_org(db, org_id=1); _seed_org(db, org_id=2, owner_id=1)
    _seed_emp(db, emp_id=1, user_id=1, org_id=1)
    _seed_emp(db, emp_id=2, user_id=1, org_id=2, name="OtherOrgSup")
    created = run(pr.create_project(org_id=1, body=_create_body(), current_user=USER, db=db))
    with pytest.raises(HTTPException) as ei:
        run(pr.update_project(org_id=1, project_id=created.id,
                              body=ProjectUpdate(supervised_by=2), current_user=USER, db=db))
    assert ei.value.status_code == 400


def test_update_project_supervisor_not_found(db):
    _seed_org(db); _seed_emp(db)
    created = run(pr.create_project(org_id=1, body=_create_body(), current_user=USER, db=db))
    with pytest.raises(HTTPException) as ei:
        run(pr.update_project(org_id=1, project_id=created.id,
                              body=ProjectUpdate(supervised_by=999), current_user=USER, db=db))
    assert ei.value.status_code == 404


def test_update_project_duplicate_name(db):
    _seed_org(db); _seed_emp(db)
    run(pr.create_project(org_id=1, body=_create_body(name="Taken"), current_user=USER, db=db))
    target = run(pr.create_project(org_id=1, body=_create_body(name="Mine"), current_user=USER, db=db))
    with pytest.raises(HTTPException) as ei:
        run(pr.update_project(org_id=1, project_id=target.id,
                              body=ProjectUpdate(name="Taken"), current_user=USER, db=db))
    assert ei.value.status_code == 400


def test_update_project_not_found(db):
    _seed_org(db)
    with pytest.raises(HTTPException) as ei:
        run(pr.update_project(org_id=1, project_id=777, body=ProjectUpdate(note="x"),
                              current_user=USER, db=db))
    assert ei.value.status_code == 404


def test_update_project_forbidden_non_member(db):
    _seed_org(db, owner_id=1)
    with pytest.raises(HTTPException) as ei:
        run(pr.update_project(org_id=1, project_id=1, body=ProjectUpdate(note="x"),
                              current_user=OTHER, db=db))
    assert ei.value.status_code == 403


# ── delete ─────────────────────────────────────────────────────────────────--

def test_delete_project_soft_deletes(db):
    _seed_org(db); _seed_emp(db)
    created = run(pr.create_project(org_id=1, body=_create_body(), current_user=USER, db=db))
    res = run(pr.delete_project(org_id=1, project_id=created.id, current_user=USER, db=db))
    assert res is None

    row = db.query(Projects).filter(Projects.id == created.id).first()
    assert row.status == ProjectsStatus.DELETED
    assert row.deleted_at is not None
    # soft-deleted rows drop out of the listing
    assert run(pr.list_projects(org_id=1, current_user=USER, db=db)) == []


def test_delete_project_not_found(db):
    _seed_org(db)
    with pytest.raises(HTTPException) as ei:
        run(pr.delete_project(org_id=1, project_id=555, current_user=USER, db=db))
    assert ei.value.status_code == 404


def test_delete_project_forbidden_non_member(db):
    _seed_org(db, owner_id=1)
    with pytest.raises(HTTPException) as ei:
        run(pr.delete_project(org_id=1, project_id=1, current_user=OTHER, db=db))
    assert ei.value.status_code == 403
