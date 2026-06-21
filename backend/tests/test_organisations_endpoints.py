"""Organisation endpoints — corp logo + ESI corp lookup (and the create/list path)."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import organisations_router as orgr
from app.api.organisations_router import OrganisationCreate
from app.core.database import Base, UserDB
from app.core.schemas import OrganisationType, Visibility

USER = SimpleNamespace(id=1)
OTHER = SimpleNamespace(id=2)
SEED_HASH = "x"  # placeholder password hash for seeded test users (not a real credential)


def _add_other(db):
    db.add(UserDB(id=2, username="other", email="o@example.com", hashed_password=SEED_HASH))
    db.commit()


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(UserDB(id=1, username="u", email="u@example.com", hashed_password=SEED_HASH))
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


# ── visibility + follow ──────────────────────────────────────────────────────

def test_visibility_syncs_is_public(db):
    pub = run(orgr.create_organisation(body=OrganisationCreate(name="Pub", visibility=Visibility.PUBLIC), current_user=USER, db=db))
    assert pub.visibility == "public" and pub.is_public is True
    grp = run(orgr.create_organisation(body=OrganisationCreate(name="Grp", visibility=Visibility.GROUP), current_user=USER, db=db))
    assert grp.visibility == "group" and grp.is_public is False
    priv = run(orgr.create_organisation(body=OrganisationCreate(name="Priv"), current_user=USER, db=db))
    assert priv.visibility == "private" and priv.is_public is False


def test_legacy_is_public_sets_visibility(db):
    out = run(orgr.create_organisation(body=OrganisationCreate(name="Legacy", is_public=True), current_user=USER, db=db))
    assert out.is_public is True and out.visibility == "public"


def test_follow_public_org_is_watch_not_membership(db):
    _add_other(db)
    org = run(orgr.create_organisation(
        body=OrganisationCreate(name="Pub", visibility=Visibility.PUBLIC), current_user=OTHER, db=db))
    out = run(orgr.follow_organisation(org_id=org.id, current_user=USER, db=db))
    assert out.following is True and out.my_role is None        # follow ≠ join/membership
    followed = run(orgr.list_followed_organisations(current_user=USER, db=db))
    assert [o.id for o in followed] == [org.id]
    run(orgr.unfollow_organisation(org_id=org.id, current_user=USER, db=db))
    assert run(orgr.list_followed_organisations(current_user=USER, db=db)) == []


def test_cannot_follow_private_org(db):
    _add_other(db)
    org = run(orgr.create_organisation(body=OrganisationCreate(name="Priv"), current_user=OTHER, db=db))
    with pytest.raises(HTTPException) as ei:
        run(orgr.follow_organisation(org_id=org.id, current_user=USER, db=db))
    assert ei.value.status_code == 403
