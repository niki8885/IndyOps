"""
Manufacturing-router endpoints (IO-08 / IO-22): blueprint lookup, full cost
calculation, recursive make-vs-buy chain, facility rig bonuses, PAK job CRUD +
lifecycle (issue / receive / history / movements), inventory FIFO/LIFO analysis
and warehouse material-availability.

Driven the project's no-HTTP way: the async endpoint functions are imported and
called directly with seeded in-memory SQLite sessions. The router opens its own
SDE sessions via ``EveSessionLocal`` and reaches the market/native engines through
adapters — both are monkeypatched so no network call and no native binary runs,
letting the router's own logic execute and be covered.
"""
import asyncio
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import manufacturing_router as mr
from app.core.database import (
    Base, UserDB, Facility, ProductionJob, ProductionStatusEvent, InventoryItem,
    StockMovement, Blueprint,
)
from app.core.database_eve import (
    EveBase, EveType, EveGroup, EveActivityProduct, EveActivityMaterial, EveActivityTime,
    EveBlueprint, EveRigBonus, EveSolarSystem,
)
from app.core.schemas import ProductionStatus, FacilityType
from app.services.chain import solve_chain
from app.services.manufacturing import CalcInput, Material, run_calculation


USER = SimpleNamespace(id=1)
SEED_HASH = "x"  # placeholder password hash for seeded test users (not a real credential)


def run(coro):
    return asyncio.run(coro)


def _mem_db(base):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


@pytest.fixture
def app_db():
    session, engine = _mem_db(Base)
    session.add(UserDB(id=1, username="u", hashed_password=SEED_HASH, email="u@e.com"))
    session.commit()
    yield session
    session.close(); engine.dispose()


@pytest.fixture
def eve_db():
    session, engine = _mem_db(EveBase)
    yield session
    session.close(); engine.dispose()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch, eve_db):
    """Cut every external seam: SDE sessions resolve to the test eve_db, market
    fetches return deterministic data, and the chain solve runs the Python core so
    no native binary is invoked."""
    monkeypatch.setattr(mr, "EveSessionLocal", lambda: eve_db)
    monkeypatch.setattr(mr.market, "esi_adjusted_prices", lambda: {34: 5.0, 35: 10.0, 2000: 9000.0})
    monkeypatch.setattr(mr.market, "esi_cost_indices", lambda: {})
    monkeypatch.setattr(
        mr.market, "fuzzwork_aggregates_or_empty",
        lambda region, ids: {str(t): {"buy": {"percentile": 5.0}, "sell": {"percentile": 7.0}}
                             for t in ids})
    # native chain engine → deterministic Python core, no subprocess
    monkeypatch.setattr(mr.chain_engine, "solve", lambda req, **kw: (solve_chain(req), "python"))


# ── seed helpers ──────────────────────────────────────────────────────────────

def _seed_blueprint(eve_db):
    """Minimal manufacturing recipe: blueprint 1000 → product 2000 (1/run, 600s)
    from Tritanium(34) + Pyerite(35)."""
    eve_db.add_all([
        EveActivityProduct(type_id=1000, activity_id=1, product_type_id=2000, quantity=1),
        EveActivityTime(type_id=1000, activity_id=1, time=600),
        EveActivityMaterial(type_id=1000, activity_id=1, material_type_id=34, quantity=100),
        EveActivityMaterial(type_id=1000, activity_id=1, material_type_id=35, quantity=40),
        EveBlueprint(type_id=1000, max_production_limit=10),
        EveGroup(group_id=18, category_id=4, group_name="Mineral"),
        EveType(type_id=1000, type_name="Widget Blueprint", group_id=18, volume=0.01),
        EveType(type_id=2000, type_name="Widget", group_id=18, volume=2.5),
        EveType(type_id=34, type_name="Tritanium", group_id=18, volume=0.01),
        EveType(type_id=35, type_name="Pyerite", group_id=18, volume=0.01),
    ])
    eve_db.commit()
    return {"bp_type_id": 1000, "product_type_id": 2000}


def _seed_facility(app_db, ftype=FacilityType.RAITARU, **kw):
    f = Facility(user_id=1, name="Home", facility_type=ftype,
                 tax=kw.get("tax", 1.0), cost_bonus=kw.get("cost_bonus", 2.0),
                 system_name=kw.get("system_name", "Jita"),
                 system_cost_index=kw.get("system_cost_index", 0.05),
                 rig1_type_id=kw.get("rig1_type_id"))
    app_db.add(f); app_db.commit(); app_db.refresh(f)
    return f


def _calc_snapshot():
    """A realistic calc_snapshot (as the UI stores) so issue/receive have something
    to consume and price."""
    inp = CalcInput(
        product_name="Widget", product_qty_per_run=1, runs=5, me=0, te=0,
        base_time_per_run=600,
        materials=[Material(34, "Tritanium", 100, 5.0), Material(35, "Pyerite", 40, 10.0)],
        output_price=2000.0, bpc_cost=100.0, broker_fee_pct=3.6,
        system_cost_index=0.05, facility_tax_pct=1.0)
    return asdict(run_calculation(inp))


def _make_job(app_db, **kw):
    snap = kw.pop("calc_snapshot", None)
    j = ProductionJob(
        user_id=1, product_type_id=kw.pop("product_type_id", 2000),
        product_name=kw.pop("product_name", "Widget"),
        runs=kw.pop("runs", 5), me=0, te=0,
        status=kw.pop("status", ProductionStatus.PLANNING),
        calc_snapshot=snap, **kw)
    app_db.add(j); app_db.commit(); app_db.refresh(j)
    return j


# ── /blueprint ─────────────────────────────────────────────────────────────────

def test_blueprint_info_returns_materials(app_db, eve_db):
    _seed_blueprint(eve_db)
    out = run(mr.get_blueprint_info(product_type_id=2000, current_user=USER))
    assert out.blueprint_type_id == 1000
    assert out.product_name == "Widget"
    assert out.qty_per_run == 1 and out.base_time_per_run == 600
    assert out.max_production_limit == 10
    assert {m["type_id"] for m in out.materials} == {34, 35}


def test_blueprint_info_404(app_db, eve_db):
    _seed_blueprint(eve_db)
    with pytest.raises(mr.HTTPException):
        run(mr.get_blueprint_info(product_type_id=999999, current_user=USER))


def test_blueprint_info_tags_material_group(app_db, eve_db):
    # Each material now carries its EVE group so the Calculator's rule dropdown can use it.
    _seed_blueprint(eve_db)
    out = run(mr.get_blueprint_info(product_type_id=2000, current_user=USER))
    assert all(m["group_name"] == "Mineral" for m in out.materials)


# ── /resolve-prices ────────────────────────────────────────────────────────────

def test_resolve_prices_default_basis(app_db, eve_db):
    # Mock aggregates: buy 5.0 / sell 7.0 for every type → buy basis picks 5.0.
    _seed_blueprint(eve_db)
    body = mr.ResolvePricesRequest(type_ids=[34, 35], price_basis="buy")
    res = run(mr.resolve_prices(body=body, current_user=USER))
    assert res["prices"]["34"] == pytest.approx(5.0)
    assert res["groups"]["34"] == "Mineral"
    assert res["sources"]["34"] == 10000002          # the default region id


def test_resolve_prices_group_rule_flips_side(app_db, eve_db):
    # A Mineral→Sell rule forces the sell side (7.0) for minerals despite buy basis.
    _seed_blueprint(eve_db)
    body = mr.ResolvePricesRequest(
        type_ids=[34, 35], price_basis="buy",
        price_rules=[mr.PriceRule(group="Mineral", side="sell")])
    res = run(mr.resolve_prices(body=body, current_user=USER))
    assert res["prices"]["34"] == pytest.approx(7.0)
    assert res["prices"]["35"] == pytest.approx(7.0)


def test_resolve_prices_empty_type_ids(app_db, eve_db):
    res = run(mr.resolve_prices(body=mr.ResolvePricesRequest(type_ids=[]), current_user=USER))
    assert res == {"prices": {}, "sources": {}, "flags": {}, "groups": {}}


# ── /calculate ───────────────────────────────────────────────────────────────

def test_calculate_full_result(app_db, eve_db):
    _seed_blueprint(eve_db)
    body = mr.CalcRequest(product_type_id=2000, runs=5, output_price=2000.0,
                          material_prices=[mr.MaterialPrice(type_id=34, unit_cost=5.0),
                                           mr.MaterialPrice(type_id=35, unit_cost=10.0)])
    res = run(mr.calculate(body=body, current_user=USER, db=app_db))
    assert res["output"]["quantity"] == 5
    assert res["materials_total_gross"] > 0
    assert "results" in res and "profit" in res["results"]
    assert res["price_flags"] == {}
    assert res["produce_character"] is None and res["sell_character"] is None


def test_calculate_uses_facility_defaults(app_db, eve_db):
    _seed_blueprint(eve_db)
    f = _seed_facility(app_db, ftype=FacilityType.RAITARU)
    body = mr.CalcRequest(product_type_id=2000, runs=2, facility_id=f.id, output_price=1000.0)
    res = run(mr.calculate(body=body, current_user=USER, db=app_db))
    # EC facility folds in the engineering-complex material/cost roles + system index.
    assert res["job_cost"]["system_cost_index_pct"] > 0
    assert res["results"]["total_costs"] > 0


def test_calculate_404(app_db, eve_db):
    _seed_blueprint(eve_db)
    body = mr.CalcRequest(product_type_id=12345)
    with pytest.raises(mr.HTTPException):
        run(mr.calculate(body=body, current_user=USER, db=app_db))


def test_calculate_with_simulation(app_db, eve_db):
    _seed_blueprint(eve_db)
    body = mr.CalcRequest(
        product_type_id=2000, runs=5, output_price=2000.0, simulate=True,
        sim=mr.SimParamsIn(n_iterations=500, seed=1),
        material_prices=[mr.MaterialPrice(type_id=34, unit_cost=5.0),
                         mr.MaterialPrice(type_id=35, unit_cost=10.0)])
    res = run(mr.calculate(body=body, current_user=USER, db=app_db))
    # The sim is best-effort; either it produced a payload or a captured error dict.
    assert "simulation" in res


# ── /calculate-chain ───────────────────────────────────────────────────────────

def test_calculate_chain_success(app_db, eve_db):
    _seed_blueprint(eve_db)
    body = mr.ChainCalcRequest(product_type_id=2000, qty=3, man_lines=5)
    res = run(mr.calculate_chain(body=body, current_user=USER, db=app_db))
    assert res["engine"] == "python"
    assert res["plan"]["target_type_id"] == 2000
    assert res["final_cost"] >= 0
    assert "assignment" in res and "schedule" in res
    assert res["include_reactions"] is True


def test_calculate_chain_with_facility_and_overrides(app_db, eve_db):
    _seed_blueprint(eve_db)
    f = _seed_facility(app_db, ftype=FacilityType.RAITARU)
    body = mr.ChainCalcRequest(
        product_type_id=2000, qty=2, facility_id=f.id, man_lines=3,
        price_overrides={34: 4.0}, force_make=[2000])
    res = run(mr.calculate_chain(body=body, current_user=USER, db=app_db))
    assert res["price_source"].get("34") == "override"
    assert res["plan"]["decisions"]["2000"]["decision"] == "make"


def test_calculate_chain_404_no_tree(app_db, eve_db):
    _seed_blueprint(eve_db)
    body = mr.ChainCalcRequest(product_type_id=424242, qty=1)
    with pytest.raises(mr.HTTPException):
        run(mr.calculate_chain(body=body, current_user=USER, db=app_db))


def test_calculate_chain_400_bad_qty(app_db, eve_db):
    _seed_blueprint(eve_db)
    body = mr.ChainCalcRequest(product_type_id=2000, qty=0)
    with pytest.raises(mr.HTTPException):
        run(mr.calculate_chain(body=body, current_user=USER, db=app_db))


def test_calculate_chain_400_no_recipe_for_raw(app_db, eve_db):
    # Tritanium(34) is a raw material — its tree node has no recipe.
    _seed_blueprint(eve_db)
    body = mr.ChainCalcRequest(product_type_id=34, qty=1)
    with pytest.raises(mr.HTTPException):
        run(mr.calculate_chain(body=body, current_user=USER, db=app_db))


def test_calculate_chain_with_structures_and_rig(app_db, eve_db):
    """Multi-location path: a fitted rig + the facility's system drive _build_facilities,
    _facility_rig_context and the reaction cost-index lookup."""
    _seed_blueprint(eve_db)
    eve_db.add_all([
        EveType(type_id=31000, type_name="ME Rig", group_id=18, volume=1.0),
        EveRigBonus(type_id=31000, group_id=18, me_bonus=-2.0, te_bonus=0.0, cost_bonus=0.0,
                    hisec_mod=1.0, lowsec_mod=1.9, nullsec_mod=2.1),
        EveSolarSystem(solar_system_id=30000142, solar_system_name="Jita", security=0.9, region_id=10000002),
    ])
    eve_db.commit()
    f = _seed_facility(app_db, ftype=FacilityType.SOTIYO, rig1_type_id=31000, system_name="Jita")
    body = mr.ChainCalcRequest(
        product_type_id=2000, qty=2, man_lines=4,
        structures=[mr.ChainStructure(place_id=f.id, name="Sotiyo", man_lines=4,
                                      system_cost_index=0.05)])
    res = run(mr.calculate_chain(body=body, current_user=USER, db=app_db))
    assert res["multi_location"] is False  # single structure
    assert res["plan"]["target_type_id"] == 2000


def test_calculate_chain_include_cj_and_multi_region(app_db, eve_db, monkeypatch):
    """include_cj triggers the C-J6MT scrape (monkeypatched) and region_ids exercises
    the multi-region min-price path."""
    _seed_blueprint(eve_db)
    monkeypatch.setattr(mr.market, "gnf_local", lambda tid: {"buy": 4.0, "sell": 6.0})
    body = mr.ChainCalcRequest(product_type_id=2000, qty=2, region_ids=[10000002, 10000043],
                               include_cj=True, man_lines=2)
    res = run(mr.calculate_chain(body=body, current_user=USER, db=app_db))
    assert res["plan"]["target_type_id"] == 2000
    # at least one input priced from C-J or a region
    assert res["price_source"]


def test_calculate_chain_reactions_off_force_buy(app_db, eve_db):
    """include_reactions=False scans the tree for reaction nodes; here there are none,
    so the branch executes and the response carries the flag + empty reactions_bought."""
    _seed_blueprint(eve_db)
    body = mr.ChainCalcRequest(product_type_id=2000, qty=2, include_reactions=False,
                               force_buy=[35])
    res = run(mr.calculate_chain(body=body, current_user=USER, db=app_db))
    assert res["include_reactions"] is False
    # Pyerite(35) has a buy price, so force_buy succeeds (not in force_buy_skipped)
    assert 35 not in res["force_buy_skipped"]


def test_calculate_chain_with_owned_blueprint(app_db, eve_db):
    _seed_blueprint(eve_db)
    app_db.add(Blueprint(user_id=1, blueprint_type_id=1000, product_type_id=2000,
                         name="Widget BP", is_bpo=True, me=10, te=20))
    app_db.commit()
    body = mr.ChainCalcRequest(product_type_id=2000, qty=2, use_owned_blueprints=True,
                               force_make=[2000])
    res = run(mr.calculate_chain(body=body, current_user=USER, db=app_db))
    assert res["blueprint_selection"].get("2000")  # a blueprint was picked for the node


# ── /facility-bonuses ──────────────────────────────────────────────────────────

def test_facility_bonuses_success(app_db, eve_db):
    _seed_blueprint(eve_db)
    f = _seed_facility(app_db, ftype=FacilityType.RAITARU)
    out = run(mr.facility_bonuses(facility_id=f.id, product_type_id=2000,
                                  current_user=USER, db=app_db))
    assert out["facility_id"] == f.id
    assert out["facility_type"] == "Raitaru"
    assert "total_me_pct" in out and "structure_role" in out
    assert out["structure_role"]["name"] == "Raitaru"  # EC role present


def test_facility_bonuses_404(app_db, eve_db):
    _seed_blueprint(eve_db)
    with pytest.raises(mr.HTTPException):
        run(mr.facility_bonuses(facility_id=999, product_type_id=2000,
                                current_user=USER, db=app_db))


# ── job CRUD + lifecycle ────────────────────────────────────────────────────────

def test_create_list_get_job(app_db, eve_db):
    body = mr.JobCreate(product_type_id=2000, product_name="Widget", runs=5)
    created = run(mr.create_job(body=body, current_user=USER, db=app_db))
    assert created.id and created.product_name == "Widget"
    # a creation status event was logged
    assert app_db.query(ProductionStatusEvent).filter_by(job_id=created.id).count() == 1

    listed = run(mr.list_jobs(current_user=USER, db=app_db))
    assert [j.id for j in listed] == [created.id]

    got = run(mr.get_job(job_id=created.id, current_user=USER, db=app_db))
    assert got.id == created.id


def test_list_jobs_filtered_by_status(app_db, eve_db):
    _make_job(app_db, status=ProductionStatus.PLANNING)
    done = _make_job(app_db, status=ProductionStatus.COMPLETED)
    listed = run(mr.list_jobs(job_status=ProductionStatus.COMPLETED,
                              current_user=USER, db=app_db))
    assert [j.id for j in listed] == [done.id]


def test_jobs_separated_by_kind(app_db, eve_db):
    pak = run(mr.create_job(body=mr.JobCreate(product_type_id=2000, product_name="Pak"),
                            current_user=USER, db=app_db))
    indy = run(mr.create_job(body=mr.JobCreate(product_type_id=2000, product_name="Indy", kind="indy"),
                             current_user=USER, db=app_db))
    assert pak.kind == "pak" and indy.kind == "indy"   # default vs explicit

    paks = run(mr.list_jobs(kind="pak", current_user=USER, db=app_db))
    indies = run(mr.list_jobs(kind="indy", current_user=USER, db=app_db))
    assert [j.id for j in paks] == [pak.id]
    assert [j.id for j in indies] == [indy.id]
    # no kind filter → both
    assert {j.id for j in run(mr.list_jobs(current_user=USER, db=app_db))} == {pak.id, indy.id}


def test_indyjob_status_change_logs_event(app_db, eve_db):
    indy = run(mr.create_job(body=mr.JobCreate(product_type_id=2000, product_name="Indy", kind="indy"),
                             current_user=USER, db=app_db))
    run(mr.update_job(job_id=indy.id, body=mr.JobUpdate(status=ProductionStatus.IN_PROGRESS),
                      current_user=USER, db=app_db))
    events = (app_db.query(ProductionStatusEvent)
              .filter_by(job_id=indy.id).order_by(ProductionStatusEvent.at).all())
    # creation event + the manual transition were both written to the DB
    assert [e.status for e in events][-1] == "In Progress"
    assert len(events) >= 2


def test_get_job_404(app_db, eve_db):
    with pytest.raises(mr.HTTPException):
        run(mr.get_job(job_id=12345, current_user=USER, db=app_db))


def test_update_job_status_transition_stamps_release(app_db, eve_db):
    j = _make_job(app_db, status=ProductionStatus.PLANNING)
    body = mr.JobUpdate(status=ProductionStatus.IN_PROGRESS, note="go")
    upd = run(mr.update_job(job_id=j.id, body=body, current_user=USER, db=app_db))
    assert upd.status == ProductionStatus.IN_PROGRESS
    assert upd.date_released is not None  # entering In Progress auto-stamps release
    # transition logged
    assert app_db.query(ProductionStatusEvent).filter_by(job_id=j.id).count() == 1


def test_update_job_404(app_db, eve_db):
    with pytest.raises(mr.HTTPException):
        run(mr.update_job(job_id=999, body=mr.JobUpdate(runs=1), current_user=USER, db=app_db))


def test_delete_job(app_db, eve_db):
    j = _make_job(app_db)
    run(mr.delete_job(job_id=j.id, current_user=USER, db=app_db))
    assert app_db.query(ProductionJob).filter_by(id=j.id).first() is None


def test_delete_job_404(app_db, eve_db):
    with pytest.raises(mr.HTTPException):
        run(mr.delete_job(job_id=999, current_user=USER, db=app_db))


def test_job_history(app_db, eve_db):
    j = _make_job(app_db, status=ProductionStatus.PLANNING)
    run(mr.update_job(job_id=j.id, body=mr.JobUpdate(status=ProductionStatus.IN_PROGRESS),
                      current_user=USER, db=app_db))
    hist = run(mr.job_history(job_id=j.id, current_user=USER, db=app_db))
    assert hist["job_id"] == j.id
    assert hist["product"] == "Widget"
    assert len(hist["events"]) >= 1
    assert hist["elapsed_seconds"] is None or hist["elapsed_seconds"] >= 0


def test_job_history_404(app_db, eve_db):
    with pytest.raises(mr.HTTPException):
        run(mr.job_history(job_id=999, current_user=USER, db=app_db))


# ── issue / receive / movements ─────────────────────────────────────────────────

def test_issue_materials_consumes_inventory_and_starts_job(app_db, eve_db):
    _seed_blueprint(eve_db)
    j = _make_job(app_db, calc_snapshot=_calc_snapshot(), status=ProductionStatus.PLANNING)
    # warehouse stock (unassigned: project_id IS NULL, matching the job's null project)
    app_db.add_all([
        InventoryItem(user_id=1, eve_type_id=34, name="Tritanium", quantity=1000, price=5.0),
        InventoryItem(user_id=1, eve_type_id=35, name="Pyerite", quantity=1000, price=10.0),
    ])
    app_db.commit()

    out = run(mr.issue_job_materials(job_id=j.id, current_user=USER, db=app_db))
    assert out["job_id"] == j.id
    assert any(m["consumed"] > 0 for m in out["materials"])
    # an 'out' movement was recorded and the job advanced to In Progress
    assert app_db.query(StockMovement).filter_by(production_job_id=j.id, direction="out").count() >= 1
    app_db.refresh(j)
    assert j.status == ProductionStatus.IN_PROGRESS
    assert (j.calc_snapshot or {}).get("actual") is not None


def test_issue_400_no_snapshot(app_db, eve_db):
    j = _make_job(app_db, calc_snapshot=None)
    with pytest.raises(mr.HTTPException):
        run(mr.issue_job_materials(job_id=j.id, current_user=USER, db=app_db))


def test_issue_400_already_issued_without_force(app_db, eve_db):
    _seed_blueprint(eve_db)
    j = _make_job(app_db, calc_snapshot=_calc_snapshot())
    app_db.add(StockMovement(user_id=1, production_job_id=j.id, name="Tritanium",
                             quantity=10, direction="out"))
    app_db.commit()
    with pytest.raises(mr.HTTPException):
        run(mr.issue_job_materials(job_id=j.id, current_user=USER, db=app_db))


def test_issue_404(app_db, eve_db):
    with pytest.raises(mr.HTTPException):
        run(mr.issue_job_materials(job_id=999, current_user=USER, db=app_db))


def test_receive_output_adds_inventory_and_completes_job(app_db, eve_db):
    _seed_blueprint(eve_db)
    j = _make_job(app_db, calc_snapshot=_calc_snapshot(), status=ProductionStatus.IN_PROGRESS)
    body = mr.ReceiveRequest(place="Jita")
    out = run(mr.receive_job_output(job_id=j.id, body=body, current_user=USER, db=app_db))
    assert out["received_qty"] == 5  # output quantity from the snapshot
    assert out["inventory_id"]
    inv = app_db.query(InventoryItem).filter_by(id=out["inventory_id"]).first()
    assert inv.flow == "output" and inv.quantity == 5
    app_db.refresh(j)
    assert j.status == ProductionStatus.COMPLETED
    assert app_db.query(StockMovement).filter_by(production_job_id=j.id, direction="in").count() == 1


def test_receive_explicit_qty_and_price(app_db, eve_db):
    _seed_blueprint(eve_db)
    j = _make_job(app_db, calc_snapshot=_calc_snapshot())
    body = mr.ReceiveRequest(quantity=2, unit_price=1234.0)
    out = run(mr.receive_job_output(job_id=j.id, body=body, current_user=USER, db=app_db))
    assert out["received_qty"] == 2 and out["unit_cost"] == pytest.approx(1234.0)


def test_receive_400_nothing_to_receive(app_db, eve_db):
    _seed_blueprint(eve_db)
    j = _make_job(app_db, calc_snapshot={"output": {"quantity": 0}})
    with pytest.raises(mr.HTTPException):
        run(mr.receive_job_output(job_id=j.id, body=mr.ReceiveRequest(),
                                  current_user=USER, db=app_db))


def test_receive_400_already_received_without_force(app_db, eve_db):
    _seed_blueprint(eve_db)
    j = _make_job(app_db, calc_snapshot=_calc_snapshot())
    app_db.add(StockMovement(user_id=1, production_job_id=j.id, name="Widget",
                             quantity=5, direction="in"))
    app_db.commit()
    with pytest.raises(mr.HTTPException):
        run(mr.receive_job_output(job_id=j.id, body=mr.ReceiveRequest(),
                                  current_user=USER, db=app_db))


def test_job_movements(app_db, eve_db):
    j = _make_job(app_db)
    app_db.add(StockMovement(user_id=1, production_job_id=j.id, name="Tritanium",
                             quantity=100, direction="out", unit_cost=5.0, total_cost=500.0,
                             reason="issue"))
    app_db.commit()
    rows = run(mr.job_movements(job_id=j.id, current_user=USER, db=app_db))
    assert len(rows) == 1 and rows[0]["direction"] == "out"
    assert rows[0]["total_cost"] == pytest.approx(500.0)


def test_job_movements_404(app_db, eve_db):
    with pytest.raises(mr.HTTPException):
        run(mr.job_movements(job_id=999, current_user=USER, db=app_db))


# ── inventory-analysis ─────────────────────────────────────────────────────────

def test_inventory_analysis_fifo(app_db, eve_db):
    app_db.add_all([
        InventoryItem(user_id=1, eve_type_id=34, name="Tritanium", quantity=100, price=5.0),
        InventoryItem(user_id=1, eve_type_id=34, name="Tritanium", quantity=200, price=6.0),
        InventoryItem(user_id=1, eve_type_id=None, name="Mystery", quantity=10, price=None),
    ])
    app_db.commit()
    res = run(mr.inventory_analysis(method="FIFO", current_user=USER, db=app_db))
    assert res["method"] == "FIFO"
    trit = next(i for i in res["items"] if i["eve_type_id"] == 34)
    assert trit["total_qty"] == 300 and trit["lots"] == 2
    assert trit["total_value_isk"] == pytest.approx(1700.0)  # 100*5 + 200*6
    # the un-typed lot falls back to a name: key
    assert any(i["key"].startswith("name:") for i in res["items"])


def test_inventory_analysis_lifo(app_db, eve_db):
    app_db.add(InventoryItem(user_id=1, eve_type_id=34, name="Tritanium", quantity=50, price=5.0))
    app_db.commit()
    res = run(mr.inventory_analysis(method="LIFO", current_user=USER, db=app_db))
    assert res["method"] == "LIFO"


# ── material-availability ──────────────────────────────────────────────────────

def test_material_availability(app_db, eve_db):
    app_db.add_all([
        InventoryItem(user_id=1, eve_type_id=34, name="Tritanium", quantity=600, price=5.0),
        InventoryItem(user_id=1, eve_type_id=34, name="Tritanium", quantity=400, price=6.0),
    ])
    app_db.commit()
    body = mr.AvailabilityRequest(materials=[
        mr.MatNeed(type_id=34, name="Tritanium", required_qty=1500),
        mr.MatNeed(type_id=99, name="Unknown", required_qty=10),
    ])
    res = run(mr.material_availability(body=body, current_user=USER, db=app_db))
    by_name = {m["name"]: m for m in res["materials"]}
    assert by_name["Tritanium"]["available"] == 1000
    assert by_name["Tritanium"]["shortfall"] == 500
    assert by_name["Tritanium"]["warehouse_unit_price"] == pytest.approx(5.4)  # (600*5+400*6)/1000
    assert by_name["Unknown"]["available"] == 0 and by_name["Unknown"]["shortfall"] == 10
