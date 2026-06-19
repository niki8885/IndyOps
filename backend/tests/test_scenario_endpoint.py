import asyncio
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.api import simulation_router as sr
from app.api.simulation_router import ScenarioRequestIn, SimParamsIn
from app.core.database import Base
from app.services import profit_sim as ps
from app.services import scenarios as sc
from app.services.chain import ChainRequest, Node, Recipe, RecipeLocation, solve_chain
from app.services.manufacturing import CalcInput, Material, run_calculation


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


USER = SimpleNamespace(id=1)


def _plan():
    loc = RecipeLocation(1, "P", "manufacturing", eiv_unit=100.0, sci=0.05, tax=0.01, scc=0.04)
    nodes = {
        1: Node(1, "Widget", 1e12, (Recipe(1, 100, 1, 600, ((2, 10),), (loc,), 100),)),
        2: Node(2, "Mat", 100.0),
    }
    return solve_chain(ChainRequest(1, 5, nodes))


def _history():
    return {
        2: ps.TypeHistory(buy=[95, 100, 105, 98, 102, 110, 90, 99],
                          sell=[100, 106, 110, 103, 108, 116, 95, 104], volume=[80000] * 8,
                          last_buy=100, anchor_buy=100),
        1: ps.TypeHistory(buy=[4800, 5000, 5200, 4900],
                          sell=[5000, 5200, 5400, 5100, 4950, 5300, 5150, 5250],
                          volume=[400] * 8, last_sell=5000, anchor_sell=5000),
    }


def _params(**kw):
    return SimParamsIn(**{"n_iterations": 2500, "seed": 1, **kw}).to_params()


def _specs():
    return [sc.SCENARIOS["market_shock_up"], sc.SCENARIOS["resource_shortage"],
            sc.SCENARIOS["tax_increase"], sc.composite_scenario(["market_shock_up", "freighter_risk"])]


def test_run_chain_scenario_analysis_persists(db):
    row = sr.run_chain_scenario_analysis(
        db, user_id=USER.id, project_id=7, plan=_plan(), production_time_s=600,
        history=_history(), params=_params(), product_name="Widget", specs=_specs(),
        broker_fee_pct=3.6, sales_tax_pct=2.0)
    assert row.id is not None
    assert row.source == "chain" and row.engine in ("fortran", "python")
    assert row.target_type_id == 1 and row.project_id == 7
    assert "expected_profit" in row.baseline
    assert len(row.outcomes) == 4
    o0 = row.outcomes[0]
    assert {"key", "name", "category", "params", "metrics", "comparison"} <= set(o0)
    assert "abs_profit_change" in o0["comparison"]
    # ranking includes the baseline + every scenario
    assert {r["rank"] for r in row.ranking} == set(range(1, 6))
    assert row.pdf[:4] == b"%PDF"


def test_run_calc_scenario_analysis_persists(db):
    inp = CalcInput(
        product_name="Widget", product_qty_per_run=1, runs=5, me=0, te=0, base_time_per_run=600,
        materials=[Material(type_id=2, name="Mat", base_qty=10, unit_cost=100.0)],
        output_price=5000.0, bpc_cost=0.0, broker_fee_pct=3.6, system_cost_index=0.05,
        facility_tax_pct=1.0)
    calc = run_calculation(inp)
    row = sr.run_calc_scenario_analysis(
        db, user_id=USER.id, project_id=None, calc=calc, product_type_id=1,
        history=_history(), params=_params(), product_name="Widget", specs=_specs())
    assert row.source == "production" and row.target_type_id == 1
    assert len(row.outcomes) == 4 and row.pdf[:4] == b"%PDF"


def test_resolve_specs_defaults_to_catalog():
    assert len(sr.resolve_specs(ScenarioRequestIn())) == len(sc.catalog())
    chosen = sr.resolve_specs(ScenarioRequestIn(keys=["market_shock_up", "nope"],
                                                composites=[["tax_increase", "freighter_risk"]],
                                                custom=[{"name": "Mine", "product_price_mult": 1.3}]))
    assert [s.category for s in chosen[-2:]] == [sc.COMPOSITE, "custom"]
    assert chosen[0].key == "market_shock_up"


def test_scenarios_catalog_endpoint():
    out = asyncio.run(sr.list_scenarios(current_user=USER))
    assert len(out["scenarios"]) >= 12
    cats = {c["category"] for c in out["categories"]}
    assert {"exogenous", "logistics", "demand", "counterfactual", "endogenous"} <= cats


def test_list_get_and_pdf_endpoints(db):
    row = sr.run_chain_scenario_analysis(
        db, user_id=USER.id, project_id=7, plan=_plan(), production_time_s=600,
        history=_history(), params=_params(), product_name="Widget", specs=_specs())
    listed = asyncio.run(sr.list_scenario_runs(project_id=7, source=None, target_type_id=None,
                                               current_user=USER, db=db))
    assert [x["analysis_id"] for x in listed["runs"]] == [row.id]
    assert listed["runs"][0]["n_scenarios"] == 4
    got = asyncio.run(sr.get_scenario_run(row.id, current_user=USER, db=db))
    assert len(got["outcomes"]) == 4 and "baseline" in got
    resp = asyncio.run(sr.get_scenario_run_pdf(row.id, current_user=USER, db=db))
    assert resp.media_type == "application/pdf" and resp.body[:4] == b"%PDF"


def test_product_rollup_pdf_combines_sim_and_scenarios(db):
    run = sr.run_chain_simulation(db, user_id=USER.id, project_id=7, plan=_plan(),
                                  production_time_s=600, history=_history(), params=_params(),
                                  product_name="Widget")
    analysis = sr.run_chain_scenario_analysis(
        db, user_id=USER.id, project_id=7, plan=_plan(), production_time_s=600,
        history=_history(), params=_params(), product_name="Widget", specs=_specs())
    # unscoped → all history for the product
    resp = asyncio.run(sr.product_rollup_pdf(1, current_user=USER, db=db))
    assert resp.media_type == "application/pdf" and resp.body[:4] == b"%PDF"
    # scoped to the current analysis (+ its MC run) → not the whole history
    scoped = asyncio.run(sr.product_rollup_pdf(1, analysis_id=analysis.id, run_id=run.id,
                                               current_user=USER, db=db))
    assert scoped.body[:4] == b"%PDF"
    # analysis-only scope (no MC run) still works
    only = asyncio.run(sr.product_rollup_pdf(1, analysis_id=analysis.id, current_user=USER, db=db))
    assert only.body[:4] == b"%PDF"


def test_user_scoping_blocks_other_users(db):
    row = sr.run_chain_scenario_analysis(
        db, user_id=USER.id, project_id=7, plan=_plan(), production_time_s=600,
        history=_history(), params=_params(), product_name="Widget", specs=_specs())
    other = SimpleNamespace(id=999)
    with pytest.raises(Exception):
        asyncio.run(sr.get_scenario_run(row.id, current_user=other, db=db))
