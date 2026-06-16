"""
Simulation orchestration + endpoints (IO-22): build a plan/calc → run the sim →
store a SimulationRun (metrics + PDF) → list / fetch / rank / roll-up. Exercised
directly against an in-memory DB (the project's no-HTTP style), passing market
history in so no network is touched.
"""
import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import simulation_router as sr
from app.api.simulation_router import SimParamsIn
from app.core.database import Base, SimulationRun
from app.services import profit_sim as ps
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
                          last_buy=100),
        1: ps.TypeHistory(buy=[4800, 5000, 5200, 4900],
                          sell=[5000, 5200, 5400, 5100, 4950, 5300, 5150, 5250],
                          volume=[400] * 8, last_sell=5000),
    }


def _params(**kw):
    return SimParamsIn(**{"n_iterations": 3000, "seed": 1, **kw}).to_params()


def test_run_chain_simulation_persists_metrics_and_pdf(db):
    run = sr.run_chain_simulation(
        db, user_id=USER.id, project_id=7, plan=_plan(), production_time_s=600,
        history=_history(), params=_params(), product_name="Widget",
        broker_fee_pct=3.6, sales_tax_pct=2.0)
    assert run.id is not None
    assert run.source == "chain" and run.engine in ("fortran", "python")
    assert run.target_type_id == 1 and run.project_id == 7
    assert "expected_profit" in run.metrics and run.metrics["n_iterations"] == 3000
    assert run.pdf[:4] == b"%PDF"
    payload = sr.run_payload(run)
    assert payload["run_id"] == run.id and "var5" in payload["summary"]


def test_run_calc_simulation_persists(db):
    inp = CalcInput(
        product_name="Widget", product_qty_per_run=1, runs=5, me=0, te=0,
        base_time_per_run=600,
        materials=[Material(type_id=2, name="Mat", base_qty=10, unit_cost=100.0)],
        output_price=5000.0, bpc_cost=0.0, broker_fee_pct=3.6, system_cost_index=0.05,
        facility_tax_pct=1.0)
    calc = run_calculation(inp)
    run = sr.run_calc_simulation(
        db, user_id=USER.id, project_id=None, calc=calc, product_type_id=1,
        history=_history(), params=_params(), product_name="Widget")
    assert run.source == "production" and run.target_type_id == 1
    assert run.metrics["expected_profit"] is not None and run.pdf[:4] == b"%PDF"


def test_list_get_and_pdf_endpoints(db):
    r = sr.run_chain_simulation(db, user_id=USER.id, project_id=7, plan=_plan(),
                                production_time_s=600, history=_history(), params=_params(),
                                product_name="Widget")
    listed = asyncio.run(sr.list_runs(project_id=7, source=None, current_user=USER, db=db))
    assert [x["run_id"] for x in listed["runs"]] == [r.id]
    got = asyncio.run(sr.get_run(r.id, current_user=USER, db=db))
    assert got["metrics"]["expected_profit"] == r.metrics["expected_profit"]
    resp = asyncio.run(sr.get_run_pdf(r.id, current_user=USER, db=db))
    assert resp.media_type == "application/pdf" and resp.body[:4] == b"%PDF"


def test_rank_and_rollup(db):
    sr.run_chain_simulation(db, user_id=USER.id, project_id=7, plan=_plan(),
                            production_time_s=600, history=_history(), params=_params(seed=1),
                            product_name="A")
    sr.run_chain_simulation(db, user_id=USER.id, project_id=7, plan=_plan(),
                            production_time_s=600, history=_history(), params=_params(seed=2),
                            product_name="B")
    run_ids = [r.id for r in db.query(SimulationRun).all()]
    ranked = asyncio.run(sr.rank_runs(sr.RankRequest(run_ids=run_ids), current_user=USER, db=db))
    assert ranked["engine"] in ("haskell", "python")
    assert {r["rank"] for r in ranked["ranked"]} == {1, 2}
    pdf_resp = asyncio.run(sr.project_rollup_pdf(7, current_user=USER, db=db))
    assert pdf_resp.media_type == "application/pdf" and pdf_resp.body[:4] == b"%PDF"


def test_user_scoping_blocks_other_users(db):
    r = sr.run_chain_simulation(db, user_id=USER.id, project_id=7, plan=_plan(),
                                production_time_s=600, history=_history(), params=_params(),
                                product_name="Widget")
    other = SimpleNamespace(id=999)
    with pytest.raises(Exception):
        asyncio.run(sr.get_run(r.id, current_user=other, db=db))
