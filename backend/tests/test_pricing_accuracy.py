"""
Production-chain pricing accuracy (IO-14): end-to-end checks that the scam-price
guard (IO-21) actually keeps an unrealistic order out of the plan's totals and
make-vs-buy — and that disabling it falls back to the raw price. Bridges
``resolve_price`` → ``from_bom`` → ``solve_chain`` (no HTTP/DB).
"""
import pytest
from app.services.chain import LocationParams, from_bom, solve_chain
from app.services.pricing import resolve_price


def _tree_widget_from_leaf():
    # W ← 4× Leaf ; Leaf is a raw buy.
    return {
        1: {"name": "W", "category_id": None, "group_name": None,
            "recipes": [{"activity": 1, "blueprint_type_id": 100, "qty_per_run": 1,
                         "base_time": 600, "max_runs": 10, "inputs": [{"type_id": 2, "qty": 4}]}]},
        2: {"name": "Leaf", "category_id": None, "group_name": None, "recipes": []},
    }


def test_scam_buy_excluded_from_chain_totals():
    # Leaf has a scam buy (0.5) but a realistic sell (80) and adjusted (100): the
    # guard must feed 80 into the chain, so the shopping line is priced at 80, not 0.5.
    price, _src, flag = resolve_price([(0.5, 1)], [(80.0, 1)], adjusted=100.0, ratio=0.3, basis="buy")
    assert price == pytest.approx(80.0) and flag and flag["original"] == pytest.approx(0.5)      # scam dropped → sell side

    plan = solve_chain(from_bom(1, 1, _tree_widget_from_leaf(),
                                {1: 1e9, 2: price}, {2: 100.0}, LocationParams(1, "P")))
    leaf = [s for s in plan.shopping_list if s.type_id == 2][0]
    assert leaf.unit == pytest.approx(80.0) and leaf.qty == 4 and leaf.total == pytest.approx(320.0)


def test_guard_disabled_uses_raw_price():
    # ratio = 0 disables the guard → the raw (scam) buy survives, no flag.
    price, _src, flag = resolve_price([(0.5, 1)], [(80.0, 1)], adjusted=100.0, ratio=0.0, basis="buy")
    assert price == pytest.approx(0.5) and flag is None


def test_scam_correction_restores_make_vs_buy():
    # Buying W costs 300. A scam 0.5 leaf makes "make" look like 2 ISK (wrongly make);
    # the corrected 80 leaf makes it 320 > 300 → correctly buy.
    tree = _tree_widget_from_leaf()
    corrected = solve_chain(from_bom(1, 1, tree, {1: 300.0, 2: 80.0}, {2: 100.0}, LocationParams(1, "P")))
    scammed = solve_chain(from_bom(1, 1, tree, {1: 300.0, 2: 0.5}, {2: 100.0}, LocationParams(1, "P")))
    assert corrected.decisions[1].decision == "buy"
    assert scammed.decisions[1].decision == "make"
