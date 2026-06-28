"""
Cross-language parity for the Reaction Planner: the native Haskell engine
(haskell/chain-engine reaction-planner) must match the Python oracle
(app.services.reaction_planner) bit-for-bit on exact rationals — same proof as
test_chain_haskell_parity.py, extended to the planner's ROI / income-per-hour /
scratch-vs-bought metrics.
"""
import pytest

from app.adapters import reaction_planner_engine as rpe
from app.services.chain import ChainRequest, Node, Recipe, RecipeLocation
from app.services.reaction_planner import Candidate, SellConfig, analyze_candidates

pytestmark = pytest.mark.skipif(
    not rpe.available(), reason="reaction-planner binary not built on this host")


def _loc(place_id=10, slot_kind="manufacturing", **kw):
    base = dict(me_mult=1.0, te_mult=1.0, sci=0.0, tax=0.0, scc=0.0,
                struct_discount=0.0, eiv_unit=0.0, bpc_unit=0.0)
    base.update(kw)
    return RecipeLocation(place_id, f"P{place_id}", slot_kind, **base)


def _candidates():
    # 1) plain manufacturing target
    simple = Candidate(1, "Simple", SellConfig(700.0), ChainRequest(1, 10, {
        1: Node(1, "Simple", None, (Recipe(1, 900, 1, 600, ((2, 5),), (_loc(),), 100),)),
        2: Node(2, "Leaf", 100.0),
    }))
    # 2) decimal sell fees + freight + ME/cost rig + reaction sub-tree
    react_loc = _loc(20, slot_kind="reaction", te_mult=0.8, sci=0.0593, tax=0.0125, eiv_unit=987.65)
    mfg_loc = _loc(10, me_mult=0.958, sci=0.04, tax=0.011, scc=0.04, struct_discount=0.021, eiv_unit=1234.56)
    messy = Candidate(40, "Messy T2",
                      SellConfig(8_888_888.88, sales_tax_pct=3.6, broker_fee_pct=1.05, freight_per_unit=1234.5),
                      ChainRequest(40, 13, {
                          40: Node(40, "Messy T2", None,
                                   (Recipe(1, 901, 2, 1234, ((41, 5), (34, 333)), (mfg_loc,), 50),)),
                          41: Node(41, "Interm", None, (Recipe(11, 902, 3, 3600, ((30, 7),), (react_loc,), 100),)),
                          30: Node(30, "Goo", 12.34),
                          34: Node(34, "Trit", 5.67),
                      }))
    # 3) T2 component with both scratch + bought variants → scratch-vs-bought delta
    tgt = Recipe(1, 903, 1, 600, ((5, 4),), (_loc(),), 100)
    rec = Recipe(11, 904, 10, 3600, ((3, 2),), (_loc(20, slot_kind="reaction"),), 100)
    scratch = ChainRequest(50, 7, {
        50: Node(50, "T2 Comp", None, (tgt,)),
        5: Node(5, "React", None, (rec,)),
        3: Node(3, "Moon", 100.0),
    })
    bought = ChainRequest(50, 7, {
        50: Node(50, "T2 Comp", None, (tgt,)),
        5: Node(5, "React", 5000.0),
        3: Node(3, "Moon", 100.0),
    })
    svb = Candidate(50, "T2 Comp", SellConfig(50_000.0, sales_tax_pct=4.0), scratch, bought=bought)
    return [simple, messy, svb]


@pytest.mark.parametrize("man_slots,react_slots", [(10, 5), (1, 1), (0, 0)])
def test_native_matches_oracle(man_slots, react_slots):
    cands = _candidates()
    py = {r.type_id: r for r in analyze_candidates(cands, man_slots, react_slots)}
    hs = {r.type_id: r for r in rpe.analyze_native(cands, man_slots, react_slots)}
    assert set(py) == set(hs)

    scalar = ["target_qty", "decision", "unit_make_cost", "total_make_cost", "unit_sell",
              "revenue", "profit", "roi", "total_time_s", "react_time_s", "man_time_s",
              "isk_per_hour", "isk_per_slot_hour", "runs_by_activity", "total_stages",
              "peak_man", "peak_react"]
    for t in py:
        a, b = py[t], hs[t]
        for f in scalar:
            assert getattr(a, f) == getattr(b, f), f"{f} mismatch on {t}: {getattr(a, f)} != {getattr(b, f)}"
        assert [(x.type_id, x.activity, x.runs, x.jobs, x.qty_out) for x in a.blueprints] \
            == [(x.type_id, x.activity, x.runs, x.jobs, x.qty_out) for x in b.blueprints]
        if a.scratch_vs_bought is None:
            assert b.scratch_vs_bought is None
        else:
            assert (a.scratch_vs_bought.cheaper, a.scratch_vs_bought.scratch_cost,
                    a.scratch_vs_bought.bought_cost, a.scratch_vs_bought.delta) == \
                   (b.scratch_vs_bought.cheaper, b.scratch_vs_bought.scratch_cost,
                    b.scratch_vs_bought.bought_cost, b.scratch_vs_bought.delta)


def test_analyze_prefers_native_engine():
    results, engine = rpe.analyze(_candidates(), 10, 5)
    assert engine == "haskell" and results
    assert results == sorted(results, key=lambda r: r.roi, reverse=True)
