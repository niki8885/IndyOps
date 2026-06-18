"""Organisation endpoints — corp logo + ESI corp lookup (and the create/list path)."""
import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import organisations_router as orgr
from app.api.organisations_router import OrganisationCreate
from app.core.database import Base, UserDB
from app.core.schemas import OrganisationType

USER = SimpleNamespace(id=1)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(UserDB(id=1, username="u", email="u@example.com", hashed_password="x"))
    session.commit()
    yield session
    session.close(); engine.dispose()


def test_corp_org_exposes_logo(db):
    out = run(orgr.create_organisation(
        body=OrganisationCreate(name="Goon Indy", org_type=OrganisationType.CORPORATION, corporation_id=98388312),
        current_user=USER, db=db))
    assert out.org_type == "Corporation"
    assert out.corporation_logo and "98388312" in out.corporation_logo

    listed = run(orgr.list_my_organisations(current_user=USER, db=db))
    assert listed[0].corporation_logo and "98388312" in listed[0].corporation_logo


def test_personal_org_has_no_logo(db):
    out = run(orgr.create_organisation(body=OrganisationCreate(name="Solo"), current_user=USER, db=db))
    assert out.org_type == "Personal"
    assert out.corporation_logo is None


def test_lookup_corporation(db, monkeypatch):
    monkeypatch.setattr(orgr.esi, "fetch_corporation",
                        lambda cid: {"name": "Goonswarm Federation", "ticker": "CONDI", "member_count": 30000})
    out = run(orgr.lookup_corporation(corporation_id=1344654522, current_user=USER))
    assert out["name"] == "Goonswarm Federation"
    assert out["ticker"] == "CONDI"
    assert "1344654522" in out["logo"]


def test_lookup_corporation_not_found(db, monkeypatch):
    def _boom(cid):
        raise RuntimeError("404")
    monkeypatch.setattr(orgr.esi, "fetch_corporation", _boom)
    with pytest.raises(Exception):
        run(orgr.lookup_corporation(corporation_id=1, current_user=USER))
