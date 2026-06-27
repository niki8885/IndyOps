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
    EsiCorpAsset, EsiCorpDivision, EsiCorpContract, EsiCorpContractItem,
)

CORP = 5000
USER = SimpleNamespace(id=1)

_WALLET = orr._SC_CORP_WALLET
_JOBS = orr._SC_CORP_JOBS
_MEMBERS = orr._SC_CORP_MEMBERS
_ALL_CORP_SCOPES = " ".join([_WALLET, _JOBS, _MEMBERS])


def _patch_names(monkeypatch, prices=None):
    """Stub the SDE/ESI name + price lookups so the corp read endpoints stay DB/network-free."""
    monkeypatch.setattr(orr, "_type_names", lambda eve, ids: {t: {"name": f"Type {t}", "volume": 1.0} for t in ids})
    monkeypatch.setattr(orr, "_station_names", lambda eve, ids: {i: f"Station {i}" for i in ids})
    monkeypatch.setattr(orr, "_system_names", lambda eve, ids: {})
    monkeypatch.setattr(orr, "_structure_names", lambda db, ids: {})
    monkeypatch.setattr(orr.market, "esi_adjusted_prices", lambda: prices or {})


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
    # can_assets / can_contracts are False here: the Director holds the wallet/jobs/members
    # scopes but not the Phase-C corp-assets / corp-contracts scopes.
    assert out["access"] == {"roles": ["Director"], "can_wallet": True, "can_jobs": True,
                             "can_members": True, "can_assets": False, "can_contracts": False,
                             "need_relink": False}
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


# ── Phase C: warehouses (corp assets) + corp contracts ──

def test_corp_warehouses_groups_by_location_and_division(db, monkeypatch):
    _patch_names(monkeypatch, prices={34: 5.0, 35: 10.0})
    db.add(LinkedCharacter(id=1, user_id=1, character_id=11, character_name="Boss",
                           corporation_id=CORP, is_active=True, status="active",
                           corp_roles=["Director"], scopes=orr._SC_CORP_ASSETS))
    db.add_all([
        EsiCorpAsset(corporation_id=CORP, item_id=1, type_id=34, quantity=100,
                     location_id=60003760, location_flag="CorpSAG1", location_type="station"),
        EsiCorpAsset(corporation_id=CORP, item_id=2, type_id=35, quantity=10,
                     location_id=60003760, location_flag="CorpSAG1", location_type="station"),
        EsiCorpAsset(corporation_id=CORP, item_id=3, type_id=34, quantity=5,
                     location_id=60003760, location_flag="CorpSAG2", location_type="station"),
        EsiCorpDivision(corporation_id=CORP, kind="hangar", division=1, name="Minerals"),
    ])
    db.commit()

    out = asyncio.run(orr.corp_warehouses(CORP, current_user=USER, db=db))
    assert out["access"]["can_assets"] is True
    assert len(out["warehouses"]) == 1
    w = out["warehouses"][0]
    assert w["location_name"] == "Station 60003760"
    divs = {d["division"]: d for d in w["divisions"]}
    # division 1 = custom name "Minerals": 100×5 + 10×10 = 600 (2 distinct types)
    assert divs[1]["name"] == "Minerals" and divs[1]["value"] == 600.0 and divs[1]["item_count"] == 2
    # division 2 = default label, 5×5 = 25
    assert divs[2]["name"] == "Corp Hangar 2" and divs[2]["value"] == 25.0
    assert out["total_value"] == 625.0


def test_corp_warehouses_access_gate_when_no_assets_scope(db, monkeypatch):
    _patch_names(monkeypatch)
    db.add(LinkedCharacter(id=1, user_id=1, character_id=11, character_name="Grunt",
                           corporation_id=CORP, is_active=True, status="active",
                           corp_roles=["Director"], scopes=_MEMBERS))   # no assets scope
    db.commit()
    out = asyncio.run(orr.corp_warehouses(CORP, current_user=USER, db=db))
    assert out["access"]["can_assets"] is False and out["warehouses"] == []


def test_corp_contracts_with_item_contents(db, monkeypatch):
    _patch_names(monkeypatch, prices={34: 5.0})
    db.add(LinkedCharacter(id=1, user_id=1, character_id=11, character_name="Boss",
                           corporation_id=CORP, is_active=True, status="active",
                           corp_roles=[], scopes=orr._SC_CORP_CONTRACTS))
    db.add(EsiCorpContract(corporation_id=CORP, contract_id=7001, type="item_exchange",
                           status="outstanding", issuer_id=11, price=1000.0, title="Sell stuff"))
    db.add_all([
        EsiCorpContractItem(corporation_id=CORP, contract_id=7001, record_id=1, type_id=34,
                            quantity=100, is_included=True),
        EsiCorpContractItem(corporation_id=CORP, contract_id=7001, record_id=2, type_id=34,
                            quantity=5, is_included=False),
    ])
    db.commit()

    out = asyncio.run(orr.corp_contracts(CORP, current_user=USER, db=db))
    assert out["access"]["can_contracts"] is True and out["count"] == 1
    c = out["contracts"][0]
    assert c["issuer"] == "Boss"            # resolved from the linked character
    assert c["item_count"] == 2
    assert c["items_value"] == 500.0        # only the offered (is_included) item: 100×5
    assert c["items"][0]["name"] == "Type 34"
