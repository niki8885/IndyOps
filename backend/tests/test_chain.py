"""
make-vs-buy core tests. Golden values are hand-computed (not produced by the
code) so a formula/recursion regression is caught — same discipline as
test_manufacturing_golden.py. Plus structural properties over the DAG.
"""
from app.services.chain import (
    ChainRequest, LocationParams, Node, Recipe, RecipeLocation, from_bom, solve_chain,
)


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
