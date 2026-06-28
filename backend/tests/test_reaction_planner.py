"""
Golden tests for the pure Reaction Planner core (oracle): per-candidate cost / ROI /
income-per-hour, the scratch-vs-bought delta, and the 10–20 component batching mark.
Plans are hand-built ChainRequests (no DB), mirroring tests/test_chain.py.
"""
import pytest

from app.services.chain import ChainRequest, Node, Recipe, RecipeLocation, solve_chain
from app.services.reaction_planner import (
    Candidate, SellConfig, analyze_candidate, analyze_candidates,
    batch_components, compare_scratch_vs_bought,
)


def _loc(place_id=1, slot_kind="manufacturing", **kw):
    base = dict(me_mult=1.0, te_mult=1.0, sci=0.0, tax=0.0, scc=0.0,
                struct_discount=0.0, eiv_unit=0.0, bpc_unit=0.0)
    base.update(kw)
    return RecipeLocation(place_id, "P", slot_kind, **base)


def test_simple_candidate_metrics():
    # Target (force-made: buy_price None) from 5× a leaf at 100 ISK, qty 10.
    req = ChainRequest(1, 10, {
        1: Node(1, "Target", None, (Recipe(1, 900, 1, 600, ((2, 5),), (_loc(),), 100),)),
        2: Node(2, "Leaf", 100.0),
    })
    res = analyze_candidate(Candidate(1, "Target", SellConfig(700.0), req), man_slots=10, react_slots=5)

    assert res.decision == "make"
    assert float(res.total_make_cost) == 5000.0          # 50 leaf × 100
    assert float(res.unit_make_cost) == 500.0
    assert float(res.unit_sell) == 700.0                 # no tax/broker/freight
    assert float(res.profit) == 2000.0                   # 7000 revenue − 5000
    assert float(res.roi) == pytest.approx(0.4)
    assert res.total_time_s == 6000                      # one mfg job, 10 runs × 600s
    assert res.react_time_s == 0 and res.man_time_s == 6000
    assert float(res.isk_per_hour) == pytest.approx(1200.0)        # 2000 / (6000/3600)
    assert float(res.isk_per_slot_hour) == pytest.approx(1200.0)
    assert res.runs_by_activity == {1: 10, 11: 0}
    assert [(b.type_id, b.runs, b.jobs) for b in res.blueprints] == [(1, 10, 1)]


def test_sell_fees_and_freight_cut_revenue():
    req = ChainRequest(1, 1, {
        1: Node(1, "T", None, (Recipe(1, 900, 1, 600, ((2, 1),), (_loc(),), 100),)),
        2: Node(2, "Leaf", 100.0),
    })
    sell = SellConfig(unit_price=1000.0, sales_tax_pct=4.0, broker_fee_pct=1.0, freight_per_unit=50.0)
    res = analyze_candidate(Candidate(1, "T", sell, req), 10, 5)
    # 1000 × (1 − 0.05) − 50 = 900 net per unit.
    assert float(res.unit_sell) == pytest.approx(900.0)
    assert float(res.profit) == pytest.approx(800.0)     # 900 − 100 make cost


def test_batch_components_marks_intermediates_10_20():
    # Target (qty 45) ← component 5 (intermediate mfg, cheap to make) ← leaf 3.
    req = ChainRequest(1, 45, {
        1: Node(1, "Target", None, (Recipe(1, 900, 1, 600, ((5, 1),), (_loc(),), 100),)),
        5: Node(5, "Component", 999.0, (Recipe(1, 901, 1, 300, ((3, 2),), (_loc(),), 100),)),
        3: Node(3, "Leaf", 10.0),
    })
    res = batch_components(analyze_candidate(Candidate(1, "Target", SellConfig(0.0), req), 10, 5))
    comp = next(b for b in res.blueprints if b.type_id == 5)
    target = next(b for b in res.blueprints if b.type_id == 1)
    assert comp.is_component is True
    assert comp.runs == 45 and comp.batch_size == 20 and comp.batches == 3   # clamp 45→20, ceil(45/20)=3
    assert target.is_component is False and target.batch_size == 0           # the target itself isn't batched


def _scratch_and_bought():
    # T2 component (1) needs 4× reaction intermediate (5). scratch makes 5 from moon goo
    # (3); bought buys 5 at 5000 each.
    target_recipe = Recipe(1, 900, 1, 600, ((5, 4),), (_loc(),), 100)
    react = Recipe(11, 901, 10, 3600, ((3, 2),), (_loc(slot_kind="reaction"),), 100)
    scratch = ChainRequest(1, 1, {
        1: Node(1, "T2", None, (target_recipe,)),
        5: Node(5, "React", None, (react,)),     # force-made (no buy price)
        3: Node(3, "Moon", 100.0),
    })
    bought = ChainRequest(1, 1, {
        1: Node(1, "T2", None, (target_recipe,)),
        5: Node(5, "React", 5000.0),             # bought (no recipes)
        3: Node(3, "Moon", 100.0),
    })
    return scratch, bought


def test_scratch_vs_bought_delta():
    scratch, bought = _scratch_and_bought()
    delta = compare_scratch_vs_bought(solve_chain(scratch), solve_chain(bought))
    assert float(delta.scratch_cost) == 200.0            # 2 moon × 100
    assert float(delta.bought_cost) == 20000.0           # 4 react × 5000
    assert delta.cheaper == "scratch"
    assert float(delta.delta) == 19800.0


def test_analyze_candidate_attaches_scratch_vs_bought():
    scratch, bought = _scratch_and_bought()
    cand = Candidate(1, "T2", SellConfig(30000.0), scratch, bought=bought)
    res = analyze_candidate(cand, 10, 5)
    assert res.scratch_vs_bought is not None
    assert res.scratch_vs_bought.cheaper == "scratch"
    assert res.runs_by_activity == {1: 1, 11: 1}


def test_analyze_candidates_sorts_by_roi():
    leaf = Node(2, "Leaf", 100.0)
    rec = (Recipe(1, 900, 1, 600, ((2, 1),), (_loc(),), 100),)
    cands = [
        Candidate(1, "Low", SellConfig(110.0), ChainRequest(1, 1, {1: Node(1, "Low", None, rec), 2: leaf})),
        Candidate(3, "High", SellConfig(500.0),
                  ChainRequest(3, 1, {3: Node(3, "High", None,
                                              (Recipe(1, 901, 1, 600, ((2, 1),), (_loc(),), 100),)), 2: leaf})),
    ]
    out = analyze_candidates(cands, 10, 5)
    assert [r.type_id for r in out] == [3, 1]             # higher ROI first
    assert out[0].roi > out[1].roi
