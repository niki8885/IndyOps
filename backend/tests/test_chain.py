"""
make-vs-buy core tests. Golden values are hand-computed (not produced by the
code) so a formula/recursion regression is caught — same discipline as
test_manufacturing_golden.py. Plus structural properties over the DAG.
"""
from app.services.chain import (
    ChainRequest, LocationParams, Node, Recipe, RecipeLocation, from_bom, solve_chain,
)
from app.services.facility_bonus import RigBonus


def _loc(place_id=10, **kw):
    base = dict(slot_kind="manufacturing", me_mult=1.0, te_mult=1.0,
                sci=0.0, tax=0.0, scc=0.0, struct_discount=0.0, eiv_unit=0.0, bpc_unit=0.0)
    base.update(kw)
    return RecipeLocation(place_id, f"P{place_id}", **base)


def _recipe(inputs, qpr=1, base_time=600, max_runs=10, activity=1, loc=None):
    return Recipe(activity, 9000, qpr, base_time, tuple(inputs), (loc or _loc(),), max_runs)


# ── golden ───────────────────────────────────────────────────────────────────

def test_golden_two_tier_make():
    # WIDGET ← 10×A + 5×RAW ; A ← 20×RAW ; RAW leaf@10.
    # A:  make 20×10 = 200  < buy 1000  → make.
    # WIDGET: make 10×200 + 5×10 = 2050 < buy 100000 → make.
    nodes = {
        1: Node(1, "WIDGET", 100000.0, (_recipe([(2, 10), (3, 5)]),)),
        2: Node(2, "A", 1000.0, (_recipe([(3, 20)]),)),
        3: Node(3, "RAW", 10.0),
    }
    plan = solve_chain(ChainRequest(1, 3, nodes))

    assert plan.decisions[1].decision == "make"
    assert plan.decisions[2].decision == "make"
    assert plan.decisions[3].decision == "buy"
    assert plan.unit_cost == 2050.0
    assert plan.total_cost == 6150.0          # 2050 × 3, integer runs divide cleanly

    # A is needed 30 (10/widget × 3), split by max_runs=10 → 3 jobs.
    a_jobs = [j for j in plan.jobs if j.type_id == 2]
    assert [j.runs for j in a_jobs] == [10, 10, 10]
    # WIDGET pulls a make-child (A) → not a tip; A's only input is RAW → a tip.
    assert [j.bounceable for j in plan.jobs if j.type_id == 1] == [False]
    assert all(j.bounceable for j in a_jobs)

    raw = [s for s in plan.shopping_list if s.type_id == 3][0]
    assert raw.qty == 615                      # 15 (widget) + 600 (3×A×200)
    assert raw.total == 6150.0


def test_golden_buy_beats_make():
    # RAW expensive → making A costs 20×500=10000 > buy 1000 → buy A, no A job.
    nodes = {
        1: Node(1, "WIDGET", 100000.0, (_recipe([(2, 10)]),)),
        2: Node(2, "A", 1000.0, (_recipe([(3, 20)]),)),
        3: Node(3, "RAW", 500.0),
    }
    plan = solve_chain(ChainRequest(1, 1, nodes))
    assert plan.decisions[2].decision == "buy"
    assert all(j.type_id != 2 for j in plan.jobs)     # A never produced
    # WIDGET makes from 10 bought A = 10000 < 100000.
    assert plan.decisions[1].decision == "make"
    a_line = [s for s in plan.shopping_list if s.type_id == 2][0]
    assert a_line.qty == 10
    assert plan.total_cost == 10000.0


def test_golden_install_me_scc():
    # One tier with ME and a full job-cost rate, hand-computed.
    # me_mult 0.9 on 1000×RAW(1.0): adj = ceil(1000×0.9)=900 → mat 900.
    # eiv_unit 1000, sci 0.05, tax 0.01, scc 0.04, no discount:
    #   install = 1000 × (0.05 + 0.01 + 0.04) = 100.  bpc 0.
    loc = _loc(me_mult=0.9, sci=0.05, tax=0.01, scc=0.04, eiv_unit=1000.0)
    nodes = {
        1: Node(1, "GADGET", 5000.0, (_recipe([(3, 1000)], loc=loc),)),
        3: Node(3, "RAW", 1.0),
    }
    plan = solve_chain(ChainRequest(1, 1, nodes))
    # per-unit make (amortised, me as fraction, no ceil): 1000×0.9×1 + 100 = 1000.
    assert plan.decisions[1].unit_make == 1000.0
    assert plan.decisions[1].decision == "make"
    job = plan.jobs[0]
    assert job.install_cost == 100.0
    # integer ME rounding for the executable job: ceil(1000×0.9)=900.
    assert job.inputs[0].qty == 900
    assert plan.total_cost == 1000.0          # 900 (RAW) + 100 install


def test_reaction_then_manufacture():
    # COMP ← reaction(activity 11) from 2×MOON ; T2 ← 4×COMP. ME doesn't touch reactions.
    react = _recipe([(30, 2)], qpr=10, base_time=3600, max_runs=100, activity=11)
    nodes = {
        20: Node(20, "T2", 9_000_000.0, (_recipe([(21, 4)]),)),
        21: Node(21, "COMP", 5000.0, (react,)),
        30: Node(30, "MOON", 100.0),
    }
    plan = solve_chain(ChainRequest(20, 5, nodes))
    # COMP make: 2×100 / 10 per run = 20 < buy 5000 → make via reaction.
    assert plan.decisions[21].decision == "make"
    assert plan.decisions[21].unit_make == 20.0
    comp_jobs = [j for j in plan.jobs if j.type_id == 21]
    assert all(j.activity == 11 and j.slot_kind == "manufacturing" for j in comp_jobs)


# ── properties ───────────────────────────────────────────────────────────────

def test_property_decision_never_above_buy():
    nodes = {
        1: Node(1, "W", 250.0, (_recipe([(2, 4)]),)),   # make 4×60=240 < 250
        2: Node(2, "B", 60.0),
    }
    plan = solve_chain(ChainRequest(1, 7, nodes))
    for d in plan.decisions.values():
        if d.unit_buy is not None and d.unit_cost is not None:
            assert d.unit_cost <= d.unit_buy + 1e-9


def test_property_shared_subtree_demand_sums():
    # RAW feeds both A and B which both feed ROOT → one merged RAW shopping line.
    nodes = {
        1: Node(1, "ROOT", 1e12, (_recipe([(2, 1), (3, 1)]),)),
        2: Node(2, "A", 1e9, (_recipe([(4, 3)]),)),
        3: Node(3, "B", 1e9, (_recipe([(4, 7)]),)),
        4: Node(4, "RAW", 1.0),
    }
    plan = solve_chain(ChainRequest(1, 1, nodes))
    raw_lines = [s for s in plan.shopping_list if s.type_id == 4]
    assert len(raw_lines) == 1               # merged, not duplicated per parent
    assert raw_lines[0].qty == 10            # 3 (via A) + 7 (via B)


def test_shared_made_intermediate_demand_sums():
    # A *made* node S feeds two made parents A and B (like a composite reaction that
    # feeds many capital components). Every parent's demand for S must be summed.
    # Regression: the make-order was a pre-order, which processes S right after the
    # FIRST parent and silently drops every later parent's demand → S's inputs and
    # the whole total cost were undercounted (Anshar margin 54% instead of ~20%).
    nodes = {
        1: Node(1, "ROOT", 1e12, (_recipe([(2, 1), (3, 1)]),)),
        2: Node(2, "A", 1e9, (_recipe([(4, 1)]),)),
        3: Node(3, "B", 1e9, (_recipe([(4, 1)]),)),
        4: Node(4, "S", 1e9, (_recipe([(5, 5)]),)),   # made shared intermediate
        5: Node(5, "RAW", 100.0),                     # bought leaf
    }
    plan = solve_chain(ChainRequest(1, 1, nodes))
    assert plan.decisions[4].decision == "make"
    raw = [s for s in plan.shopping_list if s.type_id == 5][0]
    assert raw.qty == 10                       # 2 × S × 5 RAW (NOT 5 — both parents counted)
    # phase-2 plan total must equal the phase-1 recursive unit cost (no install here).
    assert plan.total_cost == plan.unit_cost == 1000.0


def test_property_total_matches_unit_when_clean():
    # qty divides runs cleanly and me_mult 1 → phase-1 unit × qty == phase-2 total.
    nodes = {
        1: Node(1, "W", 1e9, (_recipe([(2, 2)], qpr=1, max_runs=1000),)),
        2: Node(2, "M", 50.0),
    }
    plan = solve_chain(ChainRequest(1, 8, nodes))
    assert plan.total_cost == round(plan.unit_cost * 8, 2)


def test_from_bom_builds_solvable_request():
    # shape mirrors repositories.eve.bom_tree output
    tree = {
        2000: {"name": "T2", "recipes": [{"activity": 1, "blueprint_type_id": 1000,
               "qty_per_run": 1, "base_time": 600, "max_runs": 10,
               "inputs": [{"type_id": 3000, "qty": 4}, {"type_id": 34, "qty": 100}]}]},
        3000: {"name": "COMP", "recipes": [{"activity": 11, "blueprint_type_id": 1001,
               "qty_per_run": 10, "base_time": 3600, "max_runs": 100,
               "inputs": [{"type_id": 4000, "qty": 2}]}]},
        34: {"name": "Trit", "recipes": []},
        4000: {"name": "Moon", "recipes": []},
    }
    buy = {2000: 9_000_000.0, 3000: 5000.0, 34: 5.0, 4000: 100.0}
    adj = {3000: 4000.0, 34: 4.0, 4000: 90.0}
    loc = LocationParams(place_id=1, place_name="Sotiyo", me_mult=0.95,
                         sci=0.04, tax=0.01, scc=0.04, struct_discount=0.03)
    req = from_bom(2000, 2, tree, buy, adj, loc)

    comp_loc = req.nodes[3000].recipes[0].locations[0]
    assert comp_loc.slot_kind == "reaction" and comp_loc.me_mult == 1.0   # reactions ignore ME
    hull_loc = req.nodes[2000].recipes[0].locations[0]
    assert hull_loc.slot_kind == "manufacturing" and hull_loc.me_mult == 0.95
    assert hull_loc.eiv_unit == 16400.0          # (4×4000 + 100×4) / 1

    plan = solve_chain(req)
    assert plan.unit_cost is not None
    assert plan.decisions[3000].decision == "make"   # 2×90/10 = 18 ≪ 5000


def test_unobtainable_when_no_buy_no_recipe():
    nodes = {
        1: Node(1, "W", None, (_recipe([(2, 1)]),)),
        2: Node(2, "X", None),                # no price, no recipe → dead end
    }
    plan = solve_chain(ChainRequest(1, 1, nodes))
    assert plan.decisions[2].decision == "unobtainable"
    assert plan.decisions[1].decision == "unobtainable"


# ── multi-facility (per-facility location) ─────────────────────────────────────

def _tree_one_tier(cat_id=None, group_name=None, qty=1000):
    return {
        1: {"name": "Hull", "category_id": cat_id, "group_name": group_name,
            "recipes": [{"activity": 1, "blueprint_type_id": 100, "qty_per_run": 1,
                         "base_time": 600, "max_runs": 100,
                         "inputs": [{"type_id": 2, "qty": qty}]}]},
        2: {"name": "Trit", "category_id": None, "group_name": None, "recipes": []},
    }


def test_multi_facility_core_picks_cheapest():
    # Two manufacturing facilities; Raitaru's 3% structure discount makes its install
    # cheaper → the core assigns the job there and carries its place_id end to end.
    tree = _tree_one_tier()
    buy, adj = {1: 1e12, 2: 1.0}, {2: 100.0}      # eiv_unit = 1000×100
    sotiyo = LocationParams(10, "Sotiyo", sci=0.05, tax=0.01, scc=0.04)
    raitaru = LocationParams(20, "Raitaru", sci=0.05, tax=0.01, scc=0.04, struct_discount=0.03)
    req = from_bom(1, 1, tree, buy, adj, [sotiyo, raitaru])
    assert len(req.nodes[1].recipes[0].locations) == 2          # one location per facility
    plan = solve_chain(req)
    assert plan.decisions[1].decision == "make"
    assert plan.decisions[1].place_id == 20                     # cheaper structure chosen
    assert all(j.place_id == 20 and j.place_name == "Raitaru" for j in plan.jobs)


def test_reaction_only_facility_skipped_for_manufacturing():
    # A facility that can only run reactions contributes no location to a manufacturing
    # recipe → the node has no maker here and must be bought.
    tree = _tree_one_tier()
    react_only = LocationParams(30, "Tatara", can_man=False, can_react=True)
    req = from_bom(1, 1, tree, {1: 500.0, 2: 1.0}, {2: 0.0}, [react_only])
    assert req.nodes[1].recipes == ()
    assert solve_chain(req).decisions[1].decision == "buy"


def test_facility_rig_and_ec_role_reduce_materials():
    # Large-ship rig (−2% ME) on an EC (−1% material role) for a battleship hull:
    # combined multiplicatively like run_calculation → 1000 × 0.98 × 0.99 = 970.2 → 971.
    tree = _tree_one_tier(cat_id=6, group_name="Battleship", qty=1000)
    rig = RigBonus(type_id=500, name="Standup L-Set Ship Manufacturing Efficiency",
                   me_bonus=-2.0, hisec_mod=1.0, lowsec_mod=1.9, nullsec_mod=2.1)
    fac = LocationParams(10, "Sotiyo", rigs=(rig,), band="hi", is_ec=True)
    req = from_bom(1, 1, tree, {1: 1e12, 2: 1.0}, {2: 0.0}, [fac])
    job = [j for j in solve_chain(req).jobs if j.type_id == 1][0]
    assert job.inputs[0].qty == 971


def test_rig_does_not_apply_to_wrong_category():
    # The same ship rig must NOT touch a non-ship product (category 7) → full 1000.
    tree = _tree_one_tier(cat_id=7, group_name="Hybrid Weapon", qty=1000)
    rig = RigBonus(type_id=500, name="Standup L-Set Ship Manufacturing Efficiency",
                   me_bonus=-2.0, hisec_mod=1.0, lowsec_mod=1.9, nullsec_mod=2.1)
    fac = LocationParams(10, "Sotiyo", rigs=(rig,), band="hi", is_ec=False)
    req = from_bom(1, 1, tree, {1: 1e12, 2: 1.0}, {2: 0.0}, [fac])
    job = [j for j in solve_chain(req).jobs if j.type_id == 1][0]
    assert job.inputs[0].qty == 1000


# ── owned-blueprint ME/TE + BPC cost (IO-11) ───────────────────────────────────

def test_blueprint_me_te_override_node():
    # An owned ME10/TE20 blueprint sets the node's base multipliers (0.90 / 0.80).
    tree = _tree_one_tier(qty=1000)
    req = from_bom(1, 1, tree, {1: 1e12, 2: 1.0}, {2: 0.0}, [LocationParams(1, "P")],
                   node_overrides={1: (10, 20)})
    loc = req.nodes[1].recipes[0].locations[0]
    assert loc.me_mult == 0.9 and loc.te_mult == 0.8
    job = [j for j in solve_chain(req).jobs if j.type_id == 1][0]
    assert job.inputs[0].qty == 900                       # ceil(1000 × 0.90)


def test_blueprint_me_stacks_with_rigs_and_role():
    # ME10 blueprint (0.90) × 2% ship rig × 1% EC role → 1000×0.90×0.98×0.99 = 873.18 → 874.
    tree = _tree_one_tier(cat_id=6, group_name="Battleship", qty=1000)
    rig = RigBonus(type_id=500, name="Standup L-Set Ship Manufacturing Efficiency",
                   me_bonus=-2.0, hisec_mod=1.0, lowsec_mod=1.9, nullsec_mod=2.1)
    fac = LocationParams(10, "Sotiyo", rigs=(rig,), band="hi", is_ec=True)
    req = from_bom(1, 1, tree, {1: 1e12, 2: 1.0}, {2: 0.0}, [fac], node_overrides={1: (10, 0)})
    job = [j for j in solve_chain(req).jobs if j.type_id == 1][0]
    assert job.inputs[0].qty == 874


def test_bpc_cost_folds_into_make_cost():
    # A BPC cost of 5/unit shows up as the job's bpc_cost (× output qty).
    tree = _tree_one_tier(qty=10)
    req = from_bom(1, 1, tree, {1: 1e12, 2: 1.0}, {2: 0.0}, [LocationParams(1, "P")],
                   bpc_unit={1: 5.0})
    job = [j for j in solve_chain(req).jobs if j.type_id == 1][0]
    assert job.bpc_cost == 5.0 * job.qty_out


# ── reactions: only at refineries, only reactor rigs apply (IO-15) ──────────────

def _tree_reaction(group_name="Composite"):
    return {
        1: {"name": "Reacted", "category_id": 4, "group_name": group_name,
            "recipes": [{"activity": 11, "blueprint_type_id": 100, "qty_per_run": 10,
                         "base_time": 3600, "max_runs": 100, "inputs": [{"type_id": 2, "qty": 100}]}]},
        2: {"name": "Moon Goo", "category_id": None, "group_name": None, "recipes": []},
    }


def _tatara(rig=None, **kw):
    return LocationParams(20, "Tatara", can_man=False, can_react=True,
                          rigs=(rig,) if rig else (), **kw)


def test_reaction_not_eligible_at_engineering_complex():
    # An EC (can_man only) is not eligible for a reaction → recipe dropped → buy.
    ec = LocationParams(10, "Sotiyo", can_man=True, can_react=False)
    req = from_bom(1, 10, _tree_reaction(), {1: 5000.0, 2: 1.0}, {2: 0.0}, [ec])
    assert req.nodes[1].recipes == ()
    assert solve_chain(req).decisions[1].decision == "buy"


def test_reaction_runs_at_refinery_with_reactor_rig():
    # A refinery is eligible; its reactor rig cuts reaction time, ME stays 1.0.
    rig = RigBonus(type_id=600, name="Standup L-Set Reactor Efficiency",
                   te_bonus=-20.0, cost_bonus=-10.0, hisec_mod=1.0, lowsec_mod=1.9, nullsec_mod=2.1)
    req = from_bom(1, 10, _tree_reaction(), {1: 5000.0, 2: 1.0}, {2: 0.0}, [_tatara(rig, band="hi")])
    loc = req.nodes[1].recipes[0].locations[0]
    assert loc.slot_kind == "reaction" and loc.place_id == 20
    assert loc.me_mult == 1.0          # reactions ignore ME
    assert loc.te_mult == 0.8          # 20% reactor TE applied


def test_reactor_rig_ignored_for_manufacturing():
    rig = RigBonus(type_id=600, name="Standup L-Set Reactor Efficiency",
                   te_bonus=-20.0, hisec_mod=1.0, lowsec_mod=1.9, nullsec_mod=2.1)
    tree = _tree_one_tier(cat_id=6, group_name="Battleship", qty=1000)
    req = from_bom(1, 1, tree, {1: 1e12, 2: 1.0}, {2: 0.0}, [LocationParams(10, "Sotiyo", rigs=(rig,), band="hi")])
    assert req.nodes[1].recipes[0].locations[0].te_mult == 1.0


def test_ship_rig_ignored_for_reaction():
    rig = RigBonus(type_id=500, name="Standup L-Set Ship Manufacturing Efficiency",
                   te_bonus=-20.0, hisec_mod=1.0, lowsec_mod=1.9, nullsec_mod=2.1)
    req = from_bom(1, 10, _tree_reaction(), {1: 5000.0, 2: 1.0}, {2: 0.0}, [_tatara(rig, band="hi")])
    assert req.nodes[1].recipes[0].locations[0].te_mult == 1.0


def test_reactor_subtype_matches_product_family():
    rig = RigBonus(type_id=601, name="Standup M-Set Composite Reactor Efficiency",
                   te_bonus=-10.0, hisec_mod=1.0, lowsec_mod=1.9, nullsec_mod=2.1)
    # composite product → the composite-reactor rig applies
    req_c = from_bom(1, 10, _tree_reaction("Composite"), {1: 5000.0, 2: 1.0}, {2: 0.0}, [_tatara(rig, band="hi")])
    assert req_c.nodes[1].recipes[0].locations[0].te_mult == 0.9
    # hybrid-polymer product → it does not
    req_h = from_bom(1, 10, _tree_reaction("Hybrid Polymers"), {1: 5000.0, 2: 1.0}, {2: 0.0}, [_tatara(rig, band="hi")])
    assert req_h.nodes[1].recipes[0].locations[0].te_mult == 1.0
