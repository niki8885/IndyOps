"""
Glue around the /calculate-chain endpoint: Fuzzwork price parsing, plan
serialisation, and one end-to-end run of the whole left arm
(bom_tree → from_bom → solve_chain → assign_jobs) without HTTP/DB session.
"""
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
    assert buy[34] == 5.5 and buy[99] is None        # percentile preferred, missing → None
    sell = mr._market_buy_prices(10000002, [34, 99], "sell")
    assert sell[34] == 7.5


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
    # W is made in 3 single-run jobs (max_runs 1, qty 3); a BPC with 2 runs → shortfall 1.
    from types import SimpleNamespace
    loc = RecipeLocation(1, "P", "manufacturing")
    nodes = {
        1: Node(1, "W", 1e9, (Recipe(1, 100, 1, 600, ((2, 1),), (loc,), 1),)),
        2: Node(2, "M", 1.0),
    }
    plan = solve_chain(ChainRequest(1, 3, nodes))
    bpc = SimpleNamespace(id=7, name="W BPC", is_bpo=False, me=10, te=20, runs=2, quantity=1)
    rep = mr._bp_report(plan, {1: bpc})
    assert rep and rep[0]["runs_needed"] == 3 and rep[0]["runs_owned"] == 2
    assert rep[0]["shortfall"] == 1 and rep[0]["is_bpo"] is False


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
