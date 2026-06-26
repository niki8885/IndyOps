"""Corp-ESI (Phase B) dashboard endpoint: organisations_router.corp_data.

Verifies the access-flag gating (the leak-prevention gate — personal work is only shown as
'personal', corp data only when role+scope grant it) and the real corp wallet / jobs / members
assembly. Runs the async endpoint directly against an in-memory SQLite DB; no network.
"""
import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import organisations_router as orr
from app.core.database import (
    Base, LinkedCharacter, EsiCorpWallet, EsiCorpIndustryJob, EsiCorpMember,
)

CORP = 5000
USER = SimpleNamespace(id=1)

_WALLET = orr._SC_CORP_WALLET
_JOBS = orr._SC_CORP_JOBS
_MEMBERS = orr._SC_CORP_MEMBERS
_ALL_CORP_SCOPES = " ".join([_WALLET, _JOBS, _MEMBERS])


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close(); engine.dispose()


def _call(db):
    return asyncio.run(orr.corp_data(CORP, current_user=USER, db=db))


def test_corp_data_404_when_no_char_in_corp(db):
    with pytest.raises(orr.HTTPException) as exc:
        _call(db)
    assert exc.value.status_code == 404


def test_corp_data_real_wallet_jobs_members_with_director(db):
    db.add(LinkedCharacter(id=1, user_id=1, character_id=11, character_name="Boss",
                           corporation_id=CORP, is_active=True, status="active",
                           corp_roles=["Director"], scopes=_ALL_CORP_SCOPES,
                           wallet_balance=200.0, assets_value=50.0))
    db.add_all([
        EsiCorpWallet(corporation_id=CORP, division=1, balance=1000.0),
        EsiCorpWallet(corporation_id=CORP, division=2, balance=500.0),
        EsiCorpIndustryJob(corporation_id=CORP, job_id=9001, installer_id=11,
                           activity_id=1, runs=5, status="active"),   # no product_type_id → no SDE read
        EsiCorpMember(corporation_id=CORP, character_id=11, character_name="Boss"),
        EsiCorpMember(corporation_id=CORP, character_id=12, character_name="Alt"),
    ])
    db.commit()

    out = _call(db)
    assert out["access"] == {"roles": ["Director"], "can_wallet": True, "can_jobs": True,
                             "can_members": True, "need_relink": False}
    assert out["wallet"]["total"] == 1500.0 and len(out["wallet"]["divisions"]) == 2
    assert out["jobs"]["total"] == 1 and out["jobs"]["active"] == 1
    assert out["jobs"]["rows"][0]["installer"] == "Boss"   # resolved from corp member
    assert out["members"]["count"] == 2
    mine = {m["character_id"]: m["is_mine"] for m in out["members"]["rows"]}
    assert mine[11] is True and mine[12] is False           # ★ only the user's linked char
    # personal block is the user's OWN char capital, kept separate from the corp wallet
    assert out["personal"]["total"] == 250.0


def test_corp_data_no_role_hides_corp_data_and_keeps_personal(db):
    # has the scopes but only a plain Member role → NOT allowed to see corp wallet/jobs
    db.add(LinkedCharacter(id=1, user_id=1, character_id=11, character_name="Grunt",
                           corporation_id=CORP, is_active=True, status="active",
                           corp_roles=["Member"], scopes=_ALL_CORP_SCOPES,
                           wallet_balance=10.0, assets_value=0.0))
    db.commit()

    out = _call(db)
    assert out["access"]["can_wallet"] is False and out["access"]["can_jobs"] is False
    assert out["access"]["can_members"] is True       # membership needs only the scope
    assert out["wallet"] is None                      # no corp wallet leaked
    assert out["personal"]["total"] == 10.0           # personal still shown, clearly separate


def test_corp_data_need_relink_when_no_corp_scopes(db):
    db.add(LinkedCharacter(id=1, user_id=1, character_id=11, character_name="Old",
                           corporation_id=CORP, is_active=True, status="active",
                           corp_roles=None, scopes="esi-wallet.read_character_wallet.v1"))
    db.commit()

    out = _call(db)
    assert out["access"]["need_relink"] is True
    assert out["wallet"] is None and out["jobs"] is None and out["members"] is None
