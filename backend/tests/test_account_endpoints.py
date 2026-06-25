"""Account / Tracking endpoints (orders, dashboard, currency, price-check).

Driven the project's no-HTTP way: the async endpoint functions are called directly
with seeded in-memory SQLite sessions; the only network touch (the live region book
in price-check) is monkeypatched.
"""
import asyncio
import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import account_router as ar
from app.api import characters_router as cr
from app.core.database import (
    Base, LinkedCharacter, EsiMarketOrder, EsiSkill, EsiIndustryJob, EsiContract,
    BankLedgerEntry, EsiMiningLedger, EsiWalletTransaction, EsiBlueprintCopy, InventoryItem,
    EsiContractItem,
)
from app.core.database_eve import (
    EveBase, EveType, EveStation, EveSolarSystem, EveRegion, EveGroup, EveTypeMaterial,
    EveActivityMaterial, EveActivityProduct,
)
from app.services import skills as skills_svc
from app.services import ratelimit

CID = 99
USER = SimpleNamespace(id=1)
SCOPE = "esi-markets.read_character_orders.v1"


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


def _seed_sde(eve_db):
    eve_db.add_all([
        EveType(type_id=34, type_name="Tritanium", group_id=18, volume=0.01, published=True),
        EveStation(station_id=60003760, station_name="Jita IV - Moon 4 - Caldari Navy Assembly Plant",
                   solar_system_id=30000142, region_id=10000002),
        EveSolarSystem(solar_system_id=30000142, solar_system_name="Jita", region_id=10000002),
        EveRegion(region_id=10000002, region_name="The Forge"),
    ])
    eve_db.commit()


def _seed_char(app_db, scopes=SCOPE):
    app_db.add(LinkedCharacter(id=1, user_id=1, character_id=CID, character_name="Trader",
                               scopes=scopes, is_active=True, status="active", wallet_balance=1_000_000.0))
    app_db.commit()


def _order(**kw):
    base = dict(character_id=CID, type_id=34, region_id=10000002, location_id=60003760,
                volume_total=100, volume_remain=50, min_volume=1, range="region", duration=90,
                issued=datetime.datetime(2026, 6, 20, 12, 0, 0))
    base.update(kw)
    return EsiMarketOrder(**base)


# ── /account/orders ──────────────────────────────────────────────────────────

def test_orders_splits_sides_and_enriches_names(app_db, eve_db):
    _seed_sde(eve_db)
    _seed_char(app_db)
    app_db.add_all([
        _order(order_id=1, is_buy_order=False, price=5.5),
        _order(order_id=2, is_buy_order=True, price=4.0, escrow=200.0, volume_remain=3),
    ])
    app_db.add(EsiSkill(character_id=CID, skill_id=skills_svc.SKILL_TRADE, trained_level=5))  # +20 slots
    app_db.commit()

    out = run(ar.get_orders(scope="all", current_user=USER, db=app_db, eve_db=eve_db))
    assert len(out["selling"]) == 1 and len(out["buying"]) == 1
    sell = out["selling"][0]
    assert sell["type_name"] == "Tritanium"
    assert sell["station"].startswith("Jita IV")
    assert sell["system"] == "Jita" and sell["region"] == "The Forge"
    assert sell["owner"] == "Trader"
    # summary: order-slot capacity = 5 base + 20 (Trade V); 2 orders used
    assert out["summary"]["order_slots"] == {"used": 2, "max": 25}
    assert out["summary"]["sell_isk"] == pytest.approx(5.5 * 50)
    assert out["summary"]["buy_escrow"] == pytest.approx(200.0)
    assert out["needs_scope"] == []


def test_orders_flags_missing_scope(app_db, eve_db):
    _seed_sde(eve_db)
    _seed_char(app_db, scopes="publicData")   # no market-orders scope
    out = run(ar.get_orders(scope="all", current_user=USER, db=app_db, eve_db=eve_db))
    assert out["needs_scope"] == ["Trader"]


# ── /account/orders/price-check ──────────────────────────────────────────────

def test_price_check_marks_outbid(app_db, eve_db, monkeypatch):
    ratelimit._last.clear()   # in-process cooldown is global; isolate this test
    _seed_char(app_db)
    app_db.add(_order(order_id=1, is_buy_order=False, price=10.0))
    app_db.commit()
    # a competitor sells cheaper → our order is outbid
    monkeypatch.setattr(ar.market, "esi_region_orders",
                        lambda region, type_id: [{"order_id": 555, "is_buy_order": False, "price": 9.0}])
    out = run(ar.price_check(body=ar.ScopeBody(scope="all"), current_user=USER, db=app_db))
    assert out["checked"] == 1
    assert out["prices"]["1"]["status"] == "outbid"
    assert out["prices"]["1"]["best_competitor"] == 9.0


def test_price_check_is_rate_limited(app_db, monkeypatch):
    ratelimit._last.clear()   # in-process cooldown is global; isolate this test
    _seed_char(app_db)
    monkeypatch.setattr(ar.market, "esi_region_orders", lambda r, t: [])
    first = run(ar.price_check(body=ar.ScopeBody(scope="all"), current_user=USER, db=app_db))
    assert "prices" in first
    again = run(ar.price_check(body=ar.ScopeBody(scope="all"), current_user=USER, db=app_db))
    assert getattr(again, "status_code", None) == 429    # JSONResponse, not a dict


# ── /account/dashboard + /account/currency ───────────────────────────────────

def test_dashboard_aggregates_and_currency(app_db):
    _seed_char(app_db)
    app_db.add_all([
        _order(order_id=1, is_buy_order=False, price=5.0, volume_remain=10),     # sell 50
        _order(order_id=2, is_buy_order=True, price=4.0, volume_remain=10, escrow=30.0),  # buy 40
        EsiIndustryJob(character_id=CID, job_id=1, activity_id=1, status="active"),       # mfg slot used
        EsiContract(character_id=CID, contract_id=1, status="outstanding"),
        BankLedgerEntry(user_id=1, character_id=CID, ref_id=777, amount_penny=100011, amount_isk=1000.11),
    ])
    app_db.commit()

    d = run(ar.dashboard(current_user=USER, db=app_db))
    assert len(d["characters"]) == 1
    c = d["characters"][0]
    assert c["sell_isk"] == pytest.approx(50.0) and c["buy_isk"] == pytest.approx(40.0)
    assert c["escrow"] == pytest.approx(30.0)
    assert c["slots"]["manufacturing"] == {"used": 1, "max": 1}
    assert c["jobs"]["manufacturing"] == 1
    assert c["contracts"] == 1
    assert d["totals"]["wallet"] == pytest.approx(1_000_000.0)
    # 1,000.11 ISK donated → 1000 Aureus + 11 Penny
    assert d["currency"] == {"total_penny": 100011, "aureus": 1000, "penny": 11}

    cur = run(ar.get_currency(current_user=USER, db=app_db))
    assert cur["balance"]["aureus"] == 1000 and cur["balance"]["penny"] == 11
    assert len(cur["deposits"]) == 1 and cur["deposits"][0]["amount_isk"] == pytest.approx(1000.11)


# ── /account/mining ──────────────────────────────────────────────────────────

MINING_SCOPE = "esi-industry.read_character_mining.v1"


def _seed_ore_sde(eve_db):
    # Veldspar (ore, invCategory 25) refines to Tritanium; 100 units per portion.
    eve_db.add_all([
        EveType(type_id=1230, type_name="Veldspar", group_id=462, volume=0.1,
                portion_size=100, published=True),
        EveType(type_id=34, type_name="Tritanium", group_id=18, volume=0.01, published=True),
        EveGroup(group_id=462, category_id=25, group_name="Veldspar"),
        EveTypeMaterial(type_id=1230, material_type_id=34, quantity=415),
        EveSolarSystem(solar_system_id=30000142, solar_system_name="Jita", region_id=10000002),
    ])
    eve_db.commit()


def test_mining_values_ledger_refined_at_jita(app_db, eve_db, monkeypatch):
    _seed_ore_sde(eve_db)
    _seed_char(app_db, scopes=MINING_SCOPE)
    app_db.add(EsiMiningLedger(character_id=CID, date=datetime.date(2026, 6, 20),
                               type_id=1230, solar_system_id=30000142, quantity=1000))
    app_db.commit()
    # stub Jita so the value is deterministic (no Fuzzwork call)
    monkeypatch.setattr(cr, "_jita_two_sided", lambda ids: {34: {"buy": 4.0, "sell": 5.0}})

    out = run(ar.get_mining(scope="all", start=None, end=None, basis="sell", limit=500,
                            current_user=USER, db=app_db, eve_db=eve_db))
    s = out["summary"]
    # 1000 Veldspar → 10 batches × 415 = 4150 Tritanium perfect; base yield 0.50, no skills
    # → floor(4150 × 0.50) = 2075 units × 5.0 ISK = 10,375
    assert s["total_value"] == pytest.approx(10_375.0)
    assert s["total_quantity"] == 1000 and s["type_count"] == 1
    assert s["categories"]["ore"]["value"] == pytest.approx(10_375.0)
    assert s["categories"]["ore"]["qty"] == 1000
    assert s["categories"]["gas"] == {"value": 0.0, "qty": 0}
    assert [d["date"] for d in s["series"]] == ["2026-06-20"]
    assert s["series"][0]["value"] == pytest.approx(10_375.0)
    # raw ledger row carries where/when + per-row refined value
    e = out["entries"][0]
    assert e["system_name"] == "Jita" and e["name"] == "Veldspar"
    assert e["value"] == pytest.approx(10_375.0)
    assert out["needs_scope"] == []


def test_mining_flags_missing_scope(app_db, eve_db):
    _seed_char(app_db, scopes="publicData")   # no mining scope
    out = run(ar.get_mining(scope="all", start=None, end=None, basis=None, limit=500,
                            current_user=USER, db=app_db, eve_db=eve_db))
    assert out["needs_scope"] == ["Trader"]
    assert out["summary"]["total_value"] == 0.0


# ── /account/trade-profits ────────────────────────────────────────────────────

WALLET_SCOPE = "esi-wallet.read_character_wallet.v1"


def _tx(tid, is_buy, qty, price, day, txid):
    return EsiWalletTransaction(character_id=CID, transaction_id=txid, type_id=tid,
                                is_buy=is_buy, quantity=qty, unit_price=price,
                                date=datetime.datetime(2026, 6, day, 12, 0, 0))


def test_trade_profits_fifo_with_default_fees(app_db, eve_db):
    _seed_sde(eve_db)                          # EveType 34 = Tritanium
    _seed_char(app_db, scopes=WALLET_SCOPE)    # no skills → broker 3.0%, tax 7.5%
    app_db.add_all([_tx(34, True, 100, 5.0, 1, 1), _tx(34, False, 60, 8.0, 2, 2)])
    app_db.commit()

    out = run(ar.get_trade_profits(scope="all", start=None, end=None,
                                   current_user=USER, db=app_db, eve_db=eve_db))
    assert out["needs_scope"] == [] and out["unmatched"] == []
    assert len(out["rows"]) == 1
    r = out["rows"][0]
    assert r["name"] == "Tritanium" and r["units"] == 60
    assert r["total_buy"] == 300.0 and r["total_sell"] == 480.0
    # broker 3%: 9 (buy) + 14.4 (sell); tax 7.5%: 36 → profit 480-300-9-14.4-36 = 120.6
    assert r["broker_buy"] == 9.0 and r["broker_sell"] == 14.4 and r["sales_tax"] == 36.0
    assert r["profit"] == 120.6
    assert out["summary"]["total_profit"] == 120.6


def test_trade_profits_flags_unmatched_and_missing_scope(app_db, eve_db):
    _seed_sde(eve_db)
    _seed_char(app_db, scopes="publicData")    # no wallet scope
    app_db.add(_tx(34, False, 10, 7.0, 2, 1))  # sell with no prior buy
    app_db.commit()

    out = run(ar.get_trade_profits(scope="all", start=None, end=None,
                                   current_user=USER, db=app_db, eve_db=eve_db))
    assert out["needs_scope"] == ["Trader"]
    assert out["rows"] == [] and out["summary"]["total_profit"] == 0.0
    assert out["unmatched"][0]["name"] == "Tritanium" and out["unmatched"][0]["units"] == 10


# ── /account/industry ─────────────────────────────────────────────────────────

def _seed_industry_sde(eve_db):
    # Blueprint 1001 → 1 Widget per run, consuming 100 Tritanium per run (manufacturing).
    eve_db.add_all([
        EveType(type_id=34, type_name="Tritanium", group_id=18, volume=0.01, published=True),
        EveType(type_id=9999, type_name="Widget", group_id=100, volume=1.0, published=True),
        EveType(type_id=1001, type_name="Widget Blueprint", group_id=101, published=True),
        EveActivityMaterial(type_id=1001, activity_id=1, material_type_id=34, quantity=100),
        EveActivityProduct(type_id=1001, activity_id=1, product_type_id=9999, quantity=1),
    ])
    eve_db.commit()


def test_industry_realizes_manufacturing_profit(app_db, eve_db):
    _seed_industry_sde(eve_db)
    _seed_char(app_db, scopes=WALLET_SCOPE)    # no skills → broker 3.0%, tax 7.5%
    app_db.add_all([
        EsiBlueprintCopy(character_id=CID, item_id=5001, type_id=1001, material_efficiency=0),
        EsiIndustryJob(character_id=CID, job_id=1, activity_id=1, blueprint_type_id=1001,
                       blueprint_id=5001, product_type_id=9999, runs=10, status="delivered",
                       end_date=datetime.datetime(2026, 6, 20, 12, 0, 0), cost=1000.0),
        _tx(34, True, 1000, 5.0, 20, 1),       # buy 1000 Tritanium @ 5 (cost basis)
        _tx(9999, False, 10, 1000.0, 21, 2),   # sell the 10 widgets @ 1000
    ])
    app_db.commit()

    out = run(ar.get_industry(scope="all", start=None, end=None,
                              current_user=USER, db=app_db, eve_db=eve_db))
    j = out["jobs"][0]
    # ME 0: consume 100×10 = 1000 Tritanium @ 5×1.03 (broker) = 5.15 → 5150 materials
    assert j["product_name"] == "Widget" and j["produced"] == 10
    assert j["materials_cost"] == 5150.0 and j["unit_cost"] == 615.0   # (5150+1000)/10
    assert j["sold"] == 10 and j["missing"] is False
    r = out["manufacturing"][0]
    # 10000 sell - 6150 build - 300 broker(3%) - 750 tax(7.5%) = 2800
    assert r["total_build"] == 6150.0 and r["total_sell"] == 10000.0 and r["profit"] == 2800.0
    assert out["mfg_summary"]["total_profit"] == 2800.0
    assert out["jobs_summary"]["missing_count"] == 0 and out["needs_scope"] == []


def test_industry_flags_missing_inputs_without_buys(app_db, eve_db):
    _seed_industry_sde(eve_db)
    _seed_char(app_db, scopes=WALLET_SCOPE)
    app_db.add_all([
        EsiBlueprintCopy(character_id=CID, item_id=5001, type_id=1001, material_efficiency=0),
        EsiIndustryJob(character_id=CID, job_id=2, activity_id=1, blueprint_type_id=1001,
                       blueprint_id=5001, product_type_id=9999, runs=5, status="delivered",
                       end_date=datetime.datetime(2026, 6, 20, 12, 0, 0), cost=500.0),
    ])
    app_db.commit()

    out = run(ar.get_industry(scope="all", start=None, end=None,
                              current_user=USER, db=app_db, eve_db=eve_db))
    j = out["jobs"][0]
    assert j["missing"] is True and j["materials_cost"] == 0.0 and j["produced"] == 5
    assert out["jobs_summary"]["missing_count"] == 1
    assert out["manufacturing"] == []


def test_industry_uses_reprocessed_minerals_as_cost_basis(app_db, eve_db):
    _seed_industry_sde(eve_db)
    _seed_char(app_db, scopes=WALLET_SCOPE)
    app_db.add_all([
        EsiBlueprintCopy(character_id=CID, item_id=5001, type_id=1001, material_efficiency=0),
        EsiIndustryJob(character_id=CID, job_id=3, activity_id=1, blueprint_type_id=1001,
                       blueprint_id=5001, product_type_id=9999, runs=10, status="delivered",
                       end_date=datetime.datetime(2026, 6, 20, 12, 0, 0), cost=1000.0),
        # 1000 Tritanium refined from own ore (no wallet buy) — owned cost basis @ 5 ISK
        InventoryItem(user_id=1, eve_type_id=34, name="Tritanium", quantity=1000, price=5.0,
                      flow="input", item_status="in_stock", source="reprocess",
                      created_at=datetime.datetime(2026, 6, 19, 12, 0, 0)),
    ])
    app_db.commit()

    out = run(ar.get_industry(scope="all", start=None, end=None,
                              current_user=USER, db=app_db, eve_db=eve_db))
    j = out["jobs"][0]
    # reprocessed minerals supply the cost basis → not "missing", materials = 1000 × 5
    assert j["missing"] is False and j["materials_cost"] == 5000.0
    assert out["jobs_summary"]["missing_count"] == 0


def test_industry_contract_profit(app_db, eve_db, monkeypatch):
    monkeypatch.setattr(ar.esi, "resolve_names", lambda ids: {})   # no network for acceptor name
    _seed_industry_sde(eve_db)                                     # Tritanium = type 34
    _seed_char(app_db, scopes=WALLET_SCOPE)
    app_db.add_all([
        _tx(34, True, 1000, 5.0, 18, 10),                          # cost basis: 1000 Trit @ 5
        EsiContract(character_id=CID, contract_id=500, type="item_exchange", status="finished",
                    issuer_id=CID, acceptor_id=42, price=8000.0, title="Trit sale",
                    date_completed=datetime.datetime(2026, 6, 20, 12, 0, 0)),
        EsiContractItem(character_id=CID, contract_id=500, record_id=1, type_id=34,
                        quantity=1000, is_included=True),
    ])
    app_db.commit()

    out = run(ar.get_industry(scope="all", start=None, end=None,
                              current_user=USER, db=app_db, eve_db=eve_db))
    assert len(out["contracts"]) == 1
    c = out["contracts"][0]
    assert c["title"] == "Trit sale" and c["total_sell"] == 8000.0
    # cost basis 1000 × 5×1.03 (broker on buy) = 5150; contract broker 8000×3% = 240
    assert c["total_cost"] == 5150.0 and c["broker_sell"] == 240.0
    assert c["profit"] == 2610.0 and c["missing"] is False         # 8000 - 5150 - 240
    assert out["contracts_summary"]["total_profit"] == 2610.0


def _seed_reaction_sde(eve_db):
    eve_db.add_all([
        EveType(type_id=2001, type_name="Composite Reaction Formula", group_id=200, published=True),
        EveType(type_id=8888, type_name="Composite", group_id=201, volume=1.0, published=True),
        EveActivityMaterial(type_id=2001, activity_id=11, material_type_id=34, quantity=100),
        EveActivityProduct(type_id=2001, activity_id=11, product_type_id=8888, quantity=1),
    ])
    eve_db.commit()


def test_industry_includes_reactions_and_copying(app_db, eve_db):
    _seed_industry_sde(eve_db)       # Tritanium 34, Widget BP 1001
    _seed_reaction_sde(eve_db)       # reaction formula 2001 → Composite 8888 (SDE activity 11)
    _seed_char(app_db, scopes=WALLET_SCOPE)
    app_db.add_all([
        _tx(34, True, 2000, 2.0, 18, 1),       # cost basis for the reaction inputs
        EsiIndustryJob(character_id=CID, job_id=10, activity_id=9, blueprint_type_id=2001,
                       blueprint_id=7001, product_type_id=8888, runs=5, status="delivered",
                       end_date=datetime.datetime(2026, 6, 19, 12, 0, 0), cost=0.0),
        EsiIndustryJob(character_id=CID, job_id=11, activity_id=5, blueprint_type_id=1001,
                       blueprint_id=5001, runs=3, status="delivered",
                       end_date=datetime.datetime(2026, 6, 19, 13, 0, 0), cost=100.0),
        _tx(8888, False, 5, 1000.0, 20, 2),    # sell the reacted Composite
    ])
    app_db.commit()

    out = run(ar.get_industry(scope="all", start=None, end=None,
                              current_user=USER, db=app_db, eve_db=eve_db))
    acts = {j["activity"] for j in out["jobs"]}
    assert "Reactions" in acts and "Copying" in acts
    assert any(r["name"] == "Composite" for r in out["manufacturing"])   # reaction output sold
    rj = next(j for j in out["jobs"] if j["activity"] == "Reactions")
    assert rj["materials_cost"] == 1030.0 and rj["produced"] == 5        # 500 Trit × 2×1.03
    cj = next(j for j in out["jobs"] if j["activity"] == "Copying")
    assert cj["materials_cost"] == 0.0                                   # copying costs no tracked mats


def test_industry_custom_unit_price_override(app_db, eve_db):
    _seed_industry_sde(eve_db)
    _seed_char(app_db, scopes=WALLET_SCOPE)
    app_db.add_all([
        EsiBlueprintCopy(character_id=CID, item_id=5001, type_id=1001, material_efficiency=0),
        EsiIndustryJob(character_id=CID, job_id=20, activity_id=1, blueprint_type_id=1001,
                       blueprint_id=5001, product_type_id=9999, runs=10, status="delivered",
                       end_date=datetime.datetime(2026, 6, 20, 12, 0, 0), cost=1000.0),
    ])
    app_db.commit()
    before = run(ar.get_industry(scope="all", start=None, end=None,
                                 current_user=USER, db=app_db, eve_db=eve_db))
    assert before["jobs"][0]["missing"] is True

    run(ar.set_job_override(body=ar.JobOverrideIn(job_id=20, custom_unit_price=700.0),
                            current_user=USER, db=app_db))
    after = run(ar.get_industry(scope="all", start=None, end=None,
                                current_user=USER, db=app_db, eve_db=eve_db))
    j = after["jobs"][0]
    assert j["missing"] is False and j["unit_cost"] == 700.0 and j["custom_unit_price"] == 700.0

    run(ar.set_job_override(body=ar.JobOverrideIn(job_id=20, custom_unit_price=None),
                            current_user=USER, db=app_db))      # Re-process Job — clear
    cleared = run(ar.get_industry(scope="all", start=None, end=None,
                                  current_user=USER, db=app_db, eve_db=eve_db))
    assert cleared["jobs"][0]["missing"] is True


def test_industry_contract_buy_as_cost_basis(app_db, eve_db, monkeypatch):
    monkeypatch.setattr(ar.esi, "resolve_names", lambda ids: {})
    monkeypatch.setattr(ar.market, "fuzzwork_aggregates_or_empty", lambda region, ids: {})
    _seed_industry_sde(eve_db)
    _seed_char(app_db, scopes=WALLET_SCOPE)
    app_db.add_all([
        # I accepted someone's sell contract: bought 1000 Tritanium for 5000 ISK
        EsiContract(character_id=CID, contract_id=600, type="item_exchange", status="finished",
                    issuer_id=999, acceptor_id=CID, price=5000.0,
                    date_completed=datetime.datetime(2026, 6, 18, 12, 0, 0)),
        EsiContractItem(character_id=CID, contract_id=600, record_id=1, type_id=34,
                        quantity=1000, is_included=True),
        EsiBlueprintCopy(character_id=CID, item_id=5001, type_id=1001, material_efficiency=0),
        EsiIndustryJob(character_id=CID, job_id=30, activity_id=1, blueprint_type_id=1001,
                       blueprint_id=5001, product_type_id=9999, runs=10, status="delivered",
                       end_date=datetime.datetime(2026, 6, 20, 12, 0, 0), cost=1000.0),
    ])
    app_db.commit()

    out = run(ar.get_industry(scope="all", start=None, end=None,
                              current_user=USER, db=app_db, eve_db=eve_db))
    assert out["contracts"] == []                       # a purchase, not a sale
    j = out["jobs"][0]
    assert j["missing"] is False and j["materials_cost"] == 5000.0   # 5000/1000 = 5 each
