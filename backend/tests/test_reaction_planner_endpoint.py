"""
End-to-end Reaction Planner pipeline on a seeded SDE, without HTTP/auth: enumeration →
bom_tree → scratch/bought build → engine.analyze → slot_fill. Mirrors the
test_full_left_arm_pipeline style in test_chain_endpoint.py.
"""
from app.adapters import reaction_planner_engine as rpe
from app.api import reaction_planner_router as rpr
from app.core.database_eve import (
    EveActivityMaterial, EveActivityProduct, EveActivityTime, EveBlueprint,
    EveGroup, EveMetaType, EveType,
)
from app.repositories import eve as eve_repo
from app.services import slot_fill
from app.services.chain import LocationParams, solve_chain
from app.services.reaction_planner import Candidate, SellConfig


def _seed(s):
    # T2 hull-component 2000 (meta 2) ← 4× reaction comp 3000 + 100× Trit (34).
    # Reaction comp 3000 (activity 11) ← 2× moon goo 4000, 10 per run.
    s.add_all([
        EveGroup(group_id=334, category_id=17, group_name="Construction Components", published=True),
        EveGroup(group_id=429, category_id=4, group_name="Composite", published=True),
        EveActivityProduct(type_id=1000, activity_id=1, product_type_id=2000, quantity=1),
        EveActivityProduct(type_id=1001, activity_id=11, product_type_id=3000, quantity=10),
        EveActivityMaterial(type_id=1000, activity_id=1, material_type_id=3000, quantity=4),
        EveActivityMaterial(type_id=1000, activity_id=1, material_type_id=34, quantity=100),
        EveActivityMaterial(type_id=1001, activity_id=11, material_type_id=4000, quantity=2),
        EveActivityTime(type_id=1000, activity_id=1, time=600),
        EveActivityTime(type_id=1001, activity_id=11, time=3600),
        EveBlueprint(type_id=1000, max_production_limit=10),
        EveBlueprint(type_id=1001, max_production_limit=100),
        EveType(type_id=2000, type_name="T2 Component", group_id=334, published=True),
        EveMetaType(type_id=2000, parent_type_id=0, meta_group_id=2),
        EveType(type_id=3000, type_name="Composite Goo", group_id=429, published=True),
        EveType(type_id=34, type_name="Tritanium", published=True),
        EveType(type_id=4000, type_name="Moon Goo", published=True),
    ])
    s.commit()


def test_reaction_subnode_detection():
    tree = {
        2000: {"recipes": [{"activity": 1}]},
        3000: {"recipes": [{"activity": 11}]},
        34: {"recipes": []},
    }
    assert rpr._reaction_subnode_ids(2000, tree) == {3000}


def _react_tree_with_fuel_block():
    # Final reaction (1) ← composite reaction (2) + a Fuel Block (3, which itself has a
    # manufacturing recipe). Moon goo (4) / ice (5) are bought leaves.
    return {
        1: {"name": "Final React", "group_name": "Composite", "category_id": 4,
            "recipes": [{"activity": 11, "blueprint_type_id": 90, "qty_per_run": 10, "base_time": 3600,
                         "max_runs": 100, "inputs": [{"type_id": 2, "qty": 4}, {"type_id": 3, "qty": 2}]}]},
        2: {"name": "Composite", "group_name": "Composite", "category_id": 4,
            "recipes": [{"activity": 11, "blueprint_type_id": 91, "qty_per_run": 10, "base_time": 3600,
                         "max_runs": 100, "inputs": [{"type_id": 4, "qty": 2}]}]},
        3: {"name": "Helium Fuel Block", "group_name": "Fuel Block", "category_id": 4,
            "recipes": [{"activity": 1, "blueprint_type_id": 92, "qty_per_run": 40, "base_time": 600,
                         "max_runs": 100, "inputs": [{"type_id": 5, "qty": 1}]}]},
        4: {"name": "Moon Goo", "recipes": []},
        5: {"name": "Ice Product", "recipes": []},
    }


def test_fuel_block_ids_detected_by_group():
    assert rpr._fuel_block_ids(1, _react_tree_with_fuel_block()) == {3}


def test_fuel_blocks_bought_not_built_in_scratch():
    tree = _react_tree_with_fuel_block()
    buy = {1: None, 2: 100.0, 3: 1000.0, 4: 10.0, 5: 50.0}
    fac = [LocationParams(20, "Athanor", can_man=True, can_react=True)]
    req = rpr._scratch_request(1, 10, tree, buy, {}, fac, 1.0, 1.0)
    assert req.nodes[3].recipes == ()          # fuel block recipe dropped → bought
    assert req.nodes[2].buy_price is None       # composite reaction force-made from scratch
    plan = solve_chain(req)
    assert plan.decisions[3].decision == "buy"               # fuel block bought, not produced
    assert 3 in {s.type_id for s in plan.shopping_list}
    assert plan.decisions[2].decision == "make"              # composite produced from moon goo
    assert 5 not in {s.type_id for s in plan.shopping_list}  # ice not sourced (fuel block bought)


def test_full_sweep_pipeline(eve_session):
    _seed(eve_session)

    # Enumeration finds the candidate both ways.
    t2 = eve_repo.manufactured_products_by_meta(eve_session, meta_group_id=2)
    react = eve_repo.reaction_products(eve_session)
    assert {m["type_id"] for m in t2} == {2000}
    assert {m["type_id"] for m in react} == {3000}

    tree = eve_repo.bom_tree(eve_session, 2000)
    buy = {2000: None, 3000: 5000.0, 34: 5.0, 4000: 100.0}
    adj = {}
    react_fac = LocationParams(20, "Athanor", can_man=False, can_react=True, react_lines=5)
    man_fac = LocationParams(10, "Sotiyo", can_man=True, can_react=False, man_lines=10)
    facilities = [react_fac, man_fac]

    scratch = rpr._scratch_request(2000, 10, tree, buy, adj, facilities, 1.0, 1.0)
    bought = rpr._bought_request(2000, 10, tree, buy, adj, facilities, 1.0, 1.0)
    assert bought is not None                                # 3000 is buyable → a bought variant exists

    cand = Candidate(2000, "T2 Component", SellConfig(10_000_000.0), scratch, bought=bought)
    results, engine = rpe.analyze([cand], man_slots=10, react_slots=5)
    assert engine in ("haskell", "python")
    r = results[0]

    assert r.decision == "make"
    assert r.runs_by_activity == {1: 10, 11: 4}             # 10 hull runs, 4 reaction runs
    bp_acts = {b.activity for b in r.blueprints}
    assert bp_acts == {1, 11}                               # both a mfg blueprint and a reaction formula
    # Building the composite from raw moon goo (≈20/unit) beats buying it at 5000.
    assert r.scratch_vs_bought is not None
    assert r.scratch_vs_bought.cheaper == "scratch"
    assert float(r.scratch_vs_bought.delta) > 0
    assert float(r.profit) > 0 and float(r.roi) > 0

    # Slot fill: with reaction + mfg slots, this profitable candidate is scheduled.
    sc = slot_fill.SlotCandidate(r.type_id, r.name, r.react_time_s, r.man_time_s,
                                 float(r.profit), float(r.isk_per_hour))
    fill = slot_fill.fill_slots([sc], man_slots=10, react_slots=5, horizon_s=86_400)
    assert fill.status in ("optimal", "feasible")
    assert fill.chosen and fill.chosen[0].type_id == 2000
