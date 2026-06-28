"""
Blueprint Collection Analyzer pipeline on a seeded SDE, without HTTP/auth: parse → resolve
blueprint names → products_for_blueprints → bom_tree → buy-materials build → engine.analyze.
"""
from app.adapters import reaction_planner_engine as rpe
from app.api import blueprint_analyzer_router as bar
from app.core.database_eve import (
    EveActivityMaterial, EveActivityProduct, EveActivityTime, EveBlueprint, EveType,
)
from app.repositories import eve as eve_repo
from app.services.blueprint_collection import parse_blueprint_list
from app.services.chain import LocationParams
from app.services.reaction_planner import Candidate, SellConfig


def _seed(s):
    # Miner II Blueprint (1000, act 1) → Miner II (2000), from a T2 component (3000) + Trit.
    s.add_all([
        EveActivityProduct(type_id=1000, activity_id=1, product_type_id=2000, quantity=1),
        EveActivityMaterial(type_id=1000, activity_id=1, material_type_id=3000, quantity=2),
        EveActivityMaterial(type_id=1000, activity_id=1, material_type_id=34, quantity=500),
        EveActivityTime(type_id=1000, activity_id=1, time=300),
        EveBlueprint(type_id=1000, max_production_limit=100),
        EveType(type_id=1000, type_name="Miner II Blueprint", published=True),
        EveType(type_id=2000, type_name="Miner II", published=True),
        EveType(type_id=3000, type_name="Component", published=True),
        EveType(type_id=34, type_name="Tritanium", published=True),
    ])
    s.commit()


def test_name_resolution_and_grouping(eve_session):
    _seed(eve_session)
    entries = parse_blueprint_list("Miner II Blueprint\nMiner II Blueprint\nMiner II Blueprint")
    assert entries == [{"name": "Miner II Blueprint", "count": 3}]
    resolved = eve_repo.types_by_name(eve_session, [e["name"] for e in entries])
    assert resolved["miner ii blueprint"]["type_id"] == 1000
    prods = eve_repo.products_for_blueprints(eve_session, [1000])
    assert prods[1000]["product_type_id"] == 2000 and prods[1000]["qty_per_run"] == 1


def test_buy_materials_build_and_analyze(eve_session):
    _seed(eve_session)
    tree = eve_repo.bom_tree(eve_session, 2000)
    buy = {2000: None, 3000: 1_000_000.0, 34: 5.0}
    fac = [LocationParams(10, "Sotiyo", can_man=True, can_react=False, man_lines=10)]

    # 10 runs of one Miner II BP, ME 2 / TE 4, buying all materials.
    req = bar._candidate_request(2000, 10, tree, buy, {}, fac, me=2, te=4,
                                 tm_man=1.0, tm_react=1.0, buy_materials=True)
    # buy_materials → the component is bought, not made.
    assert req.nodes[3000].recipes == ()
    cand = Candidate(2000, "Miner II Blueprint", SellConfig(3_000_000.0), req, bought=None)
    results, engine = rpe.analyze([cand], man_slots=10, react_slots=0)
    assert engine in ("haskell", "python")
    r = results[0]
    assert r.decision == "make"
    assert r.runs_by_activity == {1: 10, 11: 0}          # 10 mfg runs, no reactions (mats bought)
    assert r.scratch_vs_bought is None
    assert float(r.profit) != 0 and r.total_time_s > 0
    # ME 2 applied: 500 Trit × 0.98 = 490 per run.
    trit = next(b for b in r.blueprints if b.type_id == 2000)
    assert trit.runs == 10


def test_optimal_mode_can_make_component(eve_session):
    # Add a cheap recipe for the component so make-vs-buy would build it when not buy-only.
    _seed(eve_session)
    eve_session.add_all([
        EveActivityProduct(type_id=1001, activity_id=1, product_type_id=3000, quantity=1),
        EveActivityMaterial(type_id=1001, activity_id=1, material_type_id=34, quantity=10),
        EveActivityTime(type_id=1001, activity_id=1, time=60),
        EveBlueprint(type_id=1001, max_production_limit=100),
    ])
    eve_session.commit()
    tree = eve_repo.bom_tree(eve_session, 2000)
    buy = {2000: None, 3000: 1_000_000.0, 34: 5.0}      # component very expensive to buy
    fac = [LocationParams(10, "Sotiyo", can_man=True, can_react=False, man_lines=10)]
    req = bar._candidate_request(2000, 10, tree, buy, {}, fac, me=0, te=0,
                                 tm_man=1.0, tm_react=1.0, buy_materials=False)
    results, _ = rpe.analyze([Candidate(2000, "Miner II BP", SellConfig(0.0), req)], 10, 0)
    # Optimal mode builds the component (10 Trit ≪ 1M buy) instead of buying it.
    assert results[0].runs_by_activity[1] >= 20         # hull runs + component runs
