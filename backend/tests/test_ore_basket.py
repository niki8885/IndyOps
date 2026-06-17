import pytest

from app.services.ore_acquisition import Need
from app.services.ore_basket import BuyOption, optimize_basket


def _opt(key, kind, tid, name, source, cost, yields):
    return BuyOption(key=key, kind=kind, type_id=tid, name=name, source=source,
                     cost_per_unit=cost, yields=yields)


def test_joint_product_ore_beats_buying_minerals_separately():
    needs = [Need(34, "Tritanium", 1000), Need(35, "Pyerite", 1000)]
    options = [
        _opt("m34@jita", "mineral", 34, "Tritanium", "Jita", 5.0, {34: 1.0}),
        _opt("m35@jita", "mineral", 35, "Pyerite", "Jita", 10.0, {35: 1.0}),
        # one Scordite unit refines into both minerals → covers the basket cheaply
        _opt("o1228@jita", "ore", 1228, "Scordite", "Jita", 100.0, {34: 346.0, 35: 173.0}),
    ]
    plan = optimize_basket(needs, options)
    assert plan.status == "optimal"
    # LP buys 1000/173 = 5.78 ore → ceil 6 units × 100 = 600, far below 15,000 direct
    assert len(plan.buys) == 1
    assert plan.buys[0].type_id == 1228 and plan.buys[0].units == 6
    assert plan.total_cost == pytest.approx(600.0)
    pyerite = next(c for c in plan.coverage if c.type_id == 35)
    assert pyerite.produced == pytest.approx(6 * 173) and pyerite.surplus == pytest.approx(6 * 173 - 1000)


def test_picks_cheapest_source_for_same_ore():
    needs = [Need(35, "Pyerite", 1000)]
    options = [
        _opt("o1228@a", "ore", 1228, "Scordite", "Expensive", 100.0, {35: 173.0}),
        _opt("o1228@b", "ore", 1228, "Scordite", "Cheap", 90.0, {35: 173.0}),
    ]
    plan = optimize_basket(needs, options)
    assert plan.status == "optimal"
    assert plan.buys[0].source == "Cheap"
    assert plan.total_cost == pytest.approx(6 * 90.0)   # ceil(1000/173)=6


def test_direct_buy_used_when_no_ore_is_cheaper():
    # ore is wildly overpriced; buying the mineral directly wins
    needs = [Need(34, "Tritanium", 1000)]
    options = [
        _opt("m34@jita", "mineral", 34, "Tritanium", "Jita", 5.0, {34: 1.0}),
        _opt("o1230@jita", "ore", 1230, "Veldspar", "Jita", 1_000_000.0, {34: 400.0}),
    ]
    plan = optimize_basket(needs, options)
    assert plan.buys[0].kind == "mineral"
    assert plan.total_cost == pytest.approx(1000 * 5.0)


def test_uncoverable_mineral_is_reported_and_rest_solved():
    needs = [Need(34, "Tritanium", 1000), Need(38, "Nocxium", 500)]
    options = [_opt("m34@jita", "mineral", 34, "Tritanium", "Jita", 5.0, {34: 1.0})]
    plan = optimize_basket(needs, options)
    assert plan.status == "optimal"
    assert "Nocxium" in plan.uncoverable
    assert all(c.type_id != 38 for c in plan.coverage)
    assert plan.total_cost == pytest.approx(5000.0)


def test_no_quantities_is_empty():
    plan = optimize_basket([Need(34, "Tritanium", 0)],
                           [_opt("m34@jita", "mineral", 34, "Tritanium", "Jita", 5.0, {34: 1.0})])
    assert plan.status == "empty"
    assert plan.total_cost is None


def test_all_uncoverable_is_infeasible():
    plan = optimize_basket([Need(34, "Tritanium", 1000)], [])
    assert plan.status == "infeasible"
    assert "Tritanium" in plan.uncoverable
