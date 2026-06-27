"""
Glue around the /calculate-chain endpoint: Fuzzwork price parsing, plan
serialisation, and one end-to-end run of the whole left arm
(bom_tree → from_bom → solve_chain → assign_jobs) without HTTP/DB session.
"""
import pytest
from app.adapters import market
from app.api import manufacturing_router as mr
from app.core.database_eve import (
    EveActivityMaterial, EveActivityProduct, EveActivityTime, EveBlueprint, EveType,
)
from app.repositories import eve as eve_repo
from app.services.assignment import Line, SlotConfig, assign_jobs
from app.services.chain import LocationParams, Node, Recipe, RecipeLocation, ChainRequest, from_bom, solve_chain


def _seed(s):
    s.add_all([
        EveActivityProduct(type_id=1000, activity_id=1, product_type_id=2000, quantity=1),
        EveActivityProduct(type_id=1001, activity_id=11, product_type_id=3000, quantity=10),
        EveActivityMaterial(type_id=1000, activity_id=1, material_type_id=3000, quantity=4),
        EveActivityMaterial(type_id=1000, activity_id=1, material_type_id=34, quantity=100),
        EveActivityMaterial(type_id=1001, activity_id=11, material_type_id=4000, quantity=2),
        EveActivityTime(type_id=1000, activity_id=1, time=600),
        EveActivityTime(type_id=1001, activity_id=11, time=3600),
        EveBlueprint(type_id=1000, max_production_limit=10),
        EveBlueprint(type_id=1001, max_production_limit=100),
        EveType(type_id=2000, type_name="T2 Hull"), EveType(type_id=3000, type_name="Comp"),
        EveType(type_id=34, type_name="Trit"), EveType(type_id=4000, type_name="Moon"),
    ])
    s.commit()


def test_market_buy_prices_parses_both_sides(monkeypatch):
    agg = {
        "34": {"buy": {"percentile": 5.5, "max": 6.0}, "sell": {"percentile": 7.5, "min": 7.0}},
        "99": {"buy": {}, "sell": {}},
    }
    monkeypatch.setattr(market, "fuzzwork_aggregates_or_empty", lambda region, ids: agg)
    buy = mr._market_buy_prices(10000002, [34, 99], "buy")
    assert buy[34] == pytest.approx(5.5) and buy[99] is None        # percentile preferred, missing → None
    sell = mr._market_buy_prices(10000002, [34, 99], "sell")
    assert sell[34] == pytest.approx(7.5)


def test_plan_dict_serialises_computed_job_fields():
    loc = RecipeLocation(1, "P", "manufacturing")
    nodes = {
        1: Node(1, "W", 9999.0, (Recipe(1, 100, 1, 600, ((2, 3),), (loc,), 10),)),
        2: Node(2, "M", 10.0),
    }
    plan = solve_chain(ChainRequest(1, 2, nodes))
    d = mr._plan_dict(plan)
    assert set(d) == {"target_type_id", "target_qty", "unit_cost", "total_cost",
                      "decisions", "jobs", "shopping_list"}
    assert all(k.isdigit() or k.startswith("-") for k in d["decisions"])   # keys stringified
    job = d["jobs"][0]
    assert "make_cost" in job and "buy_fallback_total" in job              # properties included


def test_to_jsonable_floats_fractions_for_api():
    import json
    loc = RecipeLocation(1, "P", "manufacturing")
    nodes = {
        1: Node(1, "W", 9999.0, (Recipe(1, 100, 1, 600, ((2, 3),), (loc,), 10),)),
        2: Node(2, "M", 10.0),
    }
    plan = solve_chain(ChainRequest(1, 2, nodes))           # exact core → Fraction fields
    payload = mr._to_jsonable({"plan": mr._plan_dict(plan)})
    json.dumps(payload)                                     # must not raise (no Fraction leaks)
    assert isinstance(payload["plan"]["total_cost"], float)


def test_region_two_sided_parses_both_sides(monkeypatch):
    agg = {"34": {"buy": {"percentile": 5.5, "max": 6.0}, "sell": {"percentile": 7.5, "min": 7.0}},
           "99": {"buy": {}, "sell": {}}}
    monkeypatch.setattr(market, "fuzzwork_aggregates_or_empty", lambda region, ids: agg)
    out = mr._region_two_sided(10000002, [34, 99])
    assert out[34] == {"buy": 5.5, "sell": 7.5}       # percentile preferred
    assert out[99] == {"buy": None, "sell": None}     # missing → None both sides


def _two_region_data():
    # region 1 / region 2, both sides per type. Trit(34) cheap on buy in r1; Comp(3000)
    # cheaper on sell in r2.
    return {
        1: {34: {"buy": 5.0, "sell": 9.0}, 3000: {"buy": 5200.0, "sell": 5300.0}},
        2: {34: {"buy": 6.0, "sell": 7.0}, 3000: {"buy": 5100.0, "sell": 5000.0}},
    }


def test_resolve_acquire_per_region_side_takes_min():
    # r1 uses Buy, r2 uses Sell → candidates 5.0 (r1 buy) vs 7.0 (r2 sell) → min 5.0.
    prices, sources, flags = mr._resolve_acquire_prices(
        [34], [1, 2], _two_region_data(), {}, {34: 10.0}, 0.0,
        basis="buy", region_sides={1: "buy", 2: "sell"}, cj_side=None,
        rules=[], group_of={34: "Mineral"}, overrides={})
    assert prices[34] == pytest.approx(5.0) and sources[34] == 1 and flags == {}


def test_resolve_acquire_other_region_side_can_win():
    # Both regions on Sell: r1 sell 9.0 vs r2 sell 7.0 → r2 wins.
    prices, sources, _ = mr._resolve_acquire_prices(
        [34], [1, 2], _two_region_data(), {}, {34: 10.0}, 0.0,
        basis="sell", region_sides={}, cj_side=None,           # empty map → basis applies
        rules=[], group_of={34: "Mineral"}, overrides={})
    assert prices[34] == pytest.approx(7.0) and sources[34] == 2


def test_resolve_acquire_group_rule_overrides_side():
    # Default side is Sell everywhere, but a Mineral→Buy rule forces the buy side for
    # Trit (group "Mineral"): cheapest buy is r1 @ 5.0, not the sell prices (9/7).
    prices, sources, _ = mr._resolve_acquire_prices(
        [34], [1, 2], _two_region_data(), {}, {34: 10.0}, 0.0,
        basis="sell", region_sides={1: "sell", 2: "sell"}, cj_side=None,
        rules=[{"group": "Mineral", "side": "buy"}], group_of={34: "Mineral"}, overrides={})
    assert prices[34] == pytest.approx(5.0) and sources[34] == 1


def test_resolve_acquire_rule_misses_other_groups():
    # The Mineral rule must not touch Comp (group "Component"): it stays on the region
    # default Sell → cheapest sell is r2 @ 5000.
    prices, sources, _ = mr._resolve_acquire_prices(
        [3000], [1, 2], _two_region_data(), {}, {3000: 6000.0}, 0.0,
        basis="sell", region_sides={1: "sell", 2: "sell"}, cj_side=None,
        rules=[{"group": "Mineral", "side": "buy"}],
        group_of={3000: "Component"}, overrides={})
    assert prices[3000] == pytest.approx(5000.0) and sources[3000] == 2


def test_resolve_acquire_cj_side_participates():
    cj = {34: {"buy": 3.0, "sell": 4.0}}
    # C-J on Buy contributes 3.0 — cheaper than either region's buy (5/6).
    prices, sources, _ = mr._resolve_acquire_prices(
        [34], [1, 2], _two_region_data(), cj, {34: 10.0}, 0.0,
        basis="buy", region_sides={1: "buy", 2: "buy"}, cj_side="buy",
        rules=[], group_of={34: "Mineral"}, overrides={})
    assert prices[34] == pytest.approx(3.0) and sources[34] == "C-J6MT"


def test_resolve_acquire_scam_guard_falls_to_other_side():
    # r1 buy is a scam (0.1 < 30% of adjusted 10); the per-region opposite side (sell)
    # rescues it and a flag records the drop.
    data = {1: {34: {"buy": 0.1, "sell": 8.0}}}
    prices, sources, flags = mr._resolve_acquire_prices(
        [34], [1], data, {}, {34: 10.0}, 0.3,
        basis="buy", region_sides={1: "buy"}, cj_side=None,
        rules=[], group_of={34: "Mineral"}, overrides={})
    assert prices[34] == pytest.approx(8.0) and sources[34] == 1
    assert flags[34]["original"] == pytest.approx(0.1) and flags[34]["used"] == pytest.approx(8.0)


def test_resolve_acquire_delivery_folds_into_candidates():
    # Delivery (ISK/m³ × volume) is added per source before the cheapest wins: r1 buy 5.0
    # + 1×2.0 haul = 7.0 vs r2 buy 6.0 + 0 = 6.0 → r2 now wins despite a higher list price.
    prices, sources, _ = mr._resolve_acquire_prices(
        [34], [1, 2], _two_region_data(), {}, {34: 10.0}, 0.0,
        basis="buy", region_sides={1: "buy", 2: "buy"}, cj_side=None,
        rules=[], group_of={34: "Mineral"}, overrides={},
        volume_of={34: 1.0}, region_delivery={1: 2.0, 2: 0.0})
    assert prices[34] == pytest.approx(6.0) and sources[34] == 2


def test_resolve_acquire_override_wins():
    prices, sources, _ = mr._resolve_acquire_prices(
        [34], [1, 2], _two_region_data(), {}, {34: 10.0}, 0.0,
        basis="buy", region_sides={1: "buy", 2: "sell"}, cj_side=None,
        rules=[], group_of={34: "Mineral"}, overrides={34: 1.23})
    assert prices[34] == pytest.approx(1.23) and sources[34] == "override"


def test_chain_assignment_summarises_plan_by_facility():
    # The assignment summary now comes straight from the core's per-job facility
    # choice — every job is in-house at its place, nothing bounced.
    loc = RecipeLocation(10, "Sotiyo", "manufacturing", eiv_unit=100.0, sci=0.05, tax=0.01, scc=0.04)
    nodes = {
        1: Node(1, "W", 1e12, (Recipe(1, 100, 1, 600, ((2, 4),), (loc,), 100),)),
        2: Node(2, "RAW", 5.0),
    }
    plan = solve_chain(ChainRequest(1, 3, nodes))
    fac = LocationParams(10, "Sotiyo", man_lines=5, sci=0.05, tax=0.01, scc=0.04)
    asg = mr._chain_assignment(plan, [fac])
    assert asg["status"] == "optimal" and asg["bought"] == []
    assert asg["in_house"] and all(a["place_name"] == "Sotiyo" for a in asg["in_house"])
    assert asg["savings_captured"] >= 0


def test_bp_report_runs_needed_and_bpc_shortfall():
    # W needs 3 runs (qty 3); a BPC with 2 runs → shortfall 1 regardless of job batching.
    from app.services import blueprints as bp_svc
    loc = RecipeLocation(1, "P", "manufacturing")
    nodes = {
        1: Node(1, "W", 1e9, (Recipe(1, 100, 1, 600, ((2, 1),), (loc,), 1),)),
        2: Node(2, "M", 1.0),
    }
    plan = solve_chain(ChainRequest(1, 3, nodes))
    tree = {
        1: {"name": "W", "recipes": [{"activity": 1, "blueprint_type_id": 100, "qty_per_run": 1}]},
        2: {"name": "M", "recipes": []},
    }
    pool = {1: [bp_svc.OwnedBP(key="esi:1", product_type_id=1, blueprint_type_id=100,
                               name="W BPC", is_bpo=False, me=10, te=20, runs=2, quantity=1,
                               cost=None, source="esi", owner="Alice")]}
    rep = mr._bp_report(plan, tree, pool, {}, {100: "W BPC"})
    assert rep and rep[0]["runs_needed"] == 3 and rep[0]["runs_owned"] == 2
    assert rep[0]["shortfall"] == 1 and rep[0]["available"] == "bpc_short"
    assert rep[0]["owned_is_bpo"] is False


def test_force_buy_drops_recipe_in_request():
    # Dropping a node's recipes (the force-buy path) leaves it buy-only.
    tree = {
        1: {"name": "W", "category_id": None, "group_name": None,
            "recipes": [{"activity": 1, "blueprint_type_id": 100, "qty_per_run": 1,
                         "base_time": 600, "max_runs": 10, "inputs": [{"type_id": 2, "qty": 4}]}]},
        2: {"name": "RAW", "category_id": None, "group_name": None, "recipes": []},
    }
    from dataclasses import replace
    req = from_bom(1, 2, tree, {1: 9999.0, 2: 10.0}, {2: 0.0}, LocationParams(1, "P"))
    req.nodes[1] = replace(req.nodes[1], recipes=())     # what calculate_chain does for force_buy
    plan = solve_chain(req)
    assert plan.decisions[1].decision == "buy"
    assert not plan.jobs


def test_bpc_cost_folds_into_make_cost_and_total():
    """Manual blueprint (BPC) cost raises the in-house cost and the plan total by exactly
    the per-unit cost × units produced, and shows up on the job's bpc_cost."""
    tree = {
        1: {"name": "W", "category_id": None, "group_name": None,
            "recipes": [{"activity": 1, "blueprint_type_id": 100, "qty_per_run": 1,
                         "base_time": 600, "max_runs": 10, "inputs": [{"type_id": 2, "qty": 4}]}]},
        2: {"name": "RAW", "category_id": None, "group_name": None, "recipes": []},
    }
    buy = {1: None, 2: 10.0}                      # target can only be made
    base = solve_chain(from_bom(1, 3, tree, buy, {}, LocationParams(1, "P")))
    withbp = solve_chain(from_bom(1, 3, tree, buy, {}, LocationParams(1, "P"),
                                  bpc_unit={1: 1000.0}))           # 1000/unit × 3 units = 3000
    assert float(withbp.total_cost) == pytest.approx(float(base.total_cost) + 3000.0)
    assert sum(float(j.bpc_cost) for j in withbp.jobs if j.type_id == 1) == pytest.approx(3000.0)


def test_reactions_off_force_buys_reaction_nodes():
    """The reactions-off path (router scans the tree for reaction-activity nodes and adds
    them to force_buy): the reaction component is bought, so its deeper reaction inputs
    (moon goo) are not produced and never reach the shopping list."""
    from dataclasses import replace
    REACTION = 11
    tree = {
        2000: {"name": "Hull", "category_id": None, "group_name": None,
               "recipes": [{"activity": 1, "blueprint_type_id": 100, "qty_per_run": 1,
                            "base_time": 600, "max_runs": 10,
                            "inputs": [{"type_id": 3000, "qty": 4}, {"type_id": 34, "qty": 100}]}]},
        3000: {"name": "Comp", "category_id": None, "group_name": None,
               "recipes": [{"activity": REACTION, "blueprint_type_id": 101, "qty_per_run": 1,
                            "base_time": 3600, "max_runs": 100, "inputs": [{"type_id": 4000, "qty": 2}]}]},
        34: {"name": "Trit", "category_id": None, "group_name": None, "recipes": []},
        4000: {"name": "Moon", "category_id": None, "group_name": None, "recipes": []},
    }
    buy = {2000: None, 3000: 5000.0, 34: 5.0, 4000: 100.0}
    req = from_bom(2000, 1, tree, buy, {}, LocationParams(1, "P"))

    # Mirror calculate_chain's reaction-detection predicate (target excluded).
    react_ids = {tid for tid, nd in tree.items()
                 if tid != 2000 and nd["recipes"]
                 and all(rc["activity"] == REACTION for rc in nd["recipes"])}
    assert react_ids == {3000}
    for tid in react_ids:                                   # force-buy them
        req.nodes[tid] = replace(req.nodes[tid], recipes=())

    plan = solve_chain(req)
    assert plan.decisions[3000].decision == "buy"           # reaction comp bought, not made
    shop_ids = {s.type_id for s in plan.shopping_list}
    assert 3000 in shop_ids and 4000 not in shop_ids        # buy the comp; moon goo not sourced


def test_reactions_from_scratch_force_makes_reaction_nodes():
    """The reactions-from-scratch path (router force-MAKES every reaction-activity node):
    even though buying the reaction comp is cheaper, it is made in-house and its moon-goo
    input is sourced — no reaction intermediate is bought."""
    from dataclasses import replace
    REACTION = 11
    tree = {
        2000: {"name": "Hull", "category_id": None, "group_name": None,
               "recipes": [{"activity": 1, "blueprint_type_id": 100, "qty_per_run": 1,
                            "base_time": 600, "max_runs": 10,
                            "inputs": [{"type_id": 3000, "qty": 4}, {"type_id": 34, "qty": 100}]}]},
        3000: {"name": "Comp", "category_id": None, "group_name": None,
               "recipes": [{"activity": REACTION, "blueprint_type_id": 101, "qty_per_run": 1,
                            "base_time": 3600, "max_runs": 100, "inputs": [{"type_id": 4000, "qty": 2}]}]},
        34: {"name": "Trit", "category_id": None, "group_name": None, "recipes": []},
        4000: {"name": "Moon", "category_id": None, "group_name": None, "recipes": []},
    }
    # Comp is cheap to buy (1.0) vs making it from moon goo — without from-scratch the
    # solver would buy it; the force-make must override that.
    buy = {2000: None, 3000: 1.0, 34: 5.0, 4000: 100.0}
    req = from_bom(2000, 1, tree, buy, {}, LocationParams(1, "P"))

    # Mirror calculate_chain's from-scratch predicate (target excluded), then force-make.
    scratch_ids = {tid for tid, nd in tree.items()
                   if tid != 2000 and nd["recipes"]
                   and all(rc["activity"] == REACTION for rc in nd["recipes"])}
    assert scratch_ids == {3000}
    for tid in scratch_ids:
        req.nodes[tid] = replace(req.nodes[tid], buy_price=None)

    plan = solve_chain(req)
    assert plan.decisions[3000].decision == "make"          # reaction comp made, not bought
    assert 4000 in {s.type_id for s in plan.shopping_list}   # its moon goo is sourced


def test_full_left_arm_pipeline(eve_session, monkeypatch):
    _seed(eve_session)
    tree = eve_repo.bom_tree(eve_session, 2000)

    prices = {"2000": {"buy": {"percentile": 9_000_000.0}}, "3000": {"buy": {"percentile": 5000.0}},
              "34": {"buy": {"percentile": 5.0}}, "4000": {"buy": {"percentile": 100.0}}}
    monkeypatch.setattr(market, "fuzzwork_aggregates_or_empty", lambda region, ids: prices)
    buy = mr._market_buy_prices(10000002, list(tree), "buy")

    loc = LocationParams(1, "Sotiyo", me_mult=0.95, sci=0.04, tax=0.01, scc=0.04,
                         struct_discount=0.03, man_lines=10, react_lines=5)
    req = from_bom(2000, 5, tree, buy, {3000: 4000.0, 34: 4.0, 4000: 90.0}, loc)
    plan = solve_chain(req)

    # cheap reaction comp + ME-reduced hull both beat buying → both made
    assert plan.decisions[3000].decision == "make"
    assert plan.decisions[2000].decision == "make"

    cfg = SlotConfig(86_400, [Line(1, "manufacturing", 10), Line(1, "reaction", 5)])
    res = assign_jobs(plan.jobs, cfg)
    assert res.status in ("optimal", "feasible")
    # plenty of slots over 24h → nothing bounced
    assert not res.bought
