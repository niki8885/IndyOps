import pytest

from app.services.ore_acquisition import Need, Source, OreInfo, compare


def _veldspar(yield_trit=415):
    return OreInfo(1230, "Veldspar", False, 100,
                   ({"type_id": 34, "name": "Tritanium", "quantity": yield_trit},))


def test_direct_mineral_buy_when_no_ore():
    r = compare(
        target="Home", basis="sell",
        needs=[Need(34, "Tritanium", 1_000)],
        sources=[Source("jita", "Jita", cost_per_m3=0.0)],
        item_prices={"jita": {34: 5.0}},
        volumes={34: 0.01}, ores=[], effective_yield=0.9,
        mineral_ref_price={34: 5.0},
    )
    mp = r.minerals[0]
    assert mp.recommended.kind == "mineral"
    assert mp.recommended.effective_cost == pytest.approx(5.0)
    assert r.recommendation["strategy"] in ("buy_minerals", "optimal_mix")


def test_cheap_ore_beats_direct_buy():
    r = compare(
        target="Home", basis="sell",
        needs=[Need(34, "Tritanium", 1_000_000)],
        sources=[Source("jita", "Jita", cost_per_m3=0.0)],
        item_prices={"jita": {34: 5.0, 1230: 3.0}},
        volumes={34: 0.01, 1230: 0.1},
        ores=[_veldspar()], effective_yield=0.9,
        mineral_ref_price={34: 5.0},
    )
    mp = r.minerals[0]
    # per unit Veldspar: 415/100×0.9 = 3.735 Trit, value 18.675, cost 3.0 → ratio 6.225
    # effective Trit cost via ore = 5.0 / 6.225 ≈ 0.803
    assert mp.ore_best is not None
    assert mp.ore_best.effective_cost == pytest.approx(5.0 / 6.225, rel=1e-3)
    assert mp.recommended.kind == "ore"
    assert mp.recommended.via_type_id == 1230
    # full-basket recommendation prefers ore/refine here
    assert r.recommendation["strategy"] in ("buy_ore_refine", "optimal_mix")


def test_value_based_allocation_across_two_minerals():
    ore = OreInfo(1233, "Plagioclase", False, 100, (
        {"type_id": 34, "name": "Tritanium", "quantity": 175},
        {"type_id": 36, "name": "Mexallon", "quantity": 70},
    ))
    r = compare(
        target="Home", basis="sell",
        needs=[Need(34, "Tritanium", 0), Need(36, "Mexallon", 0)],
        sources=[Source("jita", "Jita", cost_per_m3=0.0)],
        item_prices={"jita": {34: 5.0, 36: 40.0, 1233: 2.0}},
        volumes={34: 0.01, 36: 0.01, 1233: 0.1},
        ores=[ore], effective_yield=0.5,
        mineral_ref_price={34: 5.0, 36: 40.0},
    )
    # per unit: trit 0.875 (value 4.375), mex 0.35 (value 14.0); total value 18.375
    # cost 2.0 → ratio 9.1875; eff = ref / ratio
    trit = next(m for m in r.minerals if m.type_id == 34)
    mex = next(m for m in r.minerals if m.type_id == 36)
    assert trit.ore_best.effective_cost == pytest.approx(5.0 / 9.1875, rel=1e-3)
    assert mex.ore_best.effective_cost == pytest.approx(40.0 / 9.1875, rel=1e-3)


def test_transport_increases_delivered_cost():
    base = compare(
        target="Home", basis="sell", needs=[Need(34, "Tritanium", 0)],
        sources=[Source("jita", "Jita", cost_per_m3=0.0)],
        item_prices={"jita": {34: 5.0}}, volumes={34: 0.01}, ores=[],
        effective_yield=0.9, mineral_ref_price={34: 5.0},
    )
    shipped = compare(
        target="Home", basis="sell", needs=[Need(34, "Tritanium", 0)],
        sources=[Source("jita", "Jita", cost_per_m3=100.0)],
        item_prices={"jita": {34: 5.0}}, volumes={34: 0.01}, ores=[],
        effective_yield=0.9, mineral_ref_price={34: 5.0},
    )
    # 0.01 m³ × 100 ISK/m³ = 1.0 added per unit
    assert base.minerals[0].direct_best.effective_cost == pytest.approx(5.0)
    assert shipped.minerals[0].direct_best.effective_cost == pytest.approx(6.0)


def test_best_cell_picks_cheapest_source():
    r = compare(
        target="Home", basis="sell", needs=[Need(34, "Tritanium", 0)],
        sources=[Source("jita", "Jita", cost_per_m3=0.0),
                 Source("cj", "C-J6MT", cost_per_m3=0.0)],
        item_prices={"jita": {34: 5.0}, "cj": {34: 4.0}},
        volumes={34: 0.01}, ores=[], effective_yield=0.9,
        mineral_ref_price={34: 4.0},
    )
    row = r.items[0]
    assert row.best.source == "C-J6MT"
    assert row.best.delivered == pytest.approx(4.0)


def test_missing_price_flags_coverage_gap():
    r = compare(
        target="Home", basis="sell",
        needs=[Need(34, "Tritanium", 1000), Need(35, "Pyerite", 1000)],
        sources=[Source("jita", "Jita", cost_per_m3=0.0)],
        item_prices={"jita": {34: 5.0, 1230: 3.0}},   # no Pyerite, Veldspar yields only Trit
        volumes={34: 0.01, 35: 0.01, 1230: 0.1},
        ores=[_veldspar()], effective_yield=0.9,
        mineral_ref_price={34: 5.0},
    )
    ore_strat = next(s for s in r.strategies if s.strategy == "buy_ore_refine")
    assert "Pyerite" in ore_strat.missing
    pyerite = next(m for m in r.minerals if m.type_id == 35)
    assert pyerite.recommended is None       # no price, no ore path


def test_per_unit_mode_has_no_basket_total():
    r = compare(
        target="Home", basis="sell", needs=[Need(34, "Tritanium", 0)],
        sources=[Source("jita", "Jita", cost_per_m3=0.0)],
        item_prices={"jita": {34: 5.0}}, volumes={34: 0.01}, ores=[],
        effective_yield=0.9, mineral_ref_price={34: 5.0},
    )
    assert all(s.total_cost is None for s in r.strategies)
    assert r.minerals[0].recommended is not None


# ── gas: compressed vs regular ───────────────────────────────────────────────
from app.services.ore_acquisition import GasInfo, compare_gas  # noqa: E402


def _gas(units=100):
    return GasInfo(reg_type_id=25268, reg_name="Fullerite-C50", reg_volume=10.0,
                   comp_type_id=62586, comp_name="Compressed Fullerite-C50",
                   comp_volume=0.05, units_per_compressed=units)


def test_gas_compressed_wins_when_transport_dominates():
    r = compare_gas(
        target="Home", basis="sell", needs=[Need(25268, "Fullerite-C50", 10_000)],
        sources=[Source("jita", "Jita", cost_per_m3=1000.0)],
        item_prices={"jita": {25268: 500.0, 62586: 49000.0}},
        volumes={25268: 10.0, 62586: 0.05},
        gas_infos=[_gas(100)], decompression_loss=0.05,
    )
    g = r.gases[0]
    assert g.reg_best.effective_cost == pytest.approx(10_500.0)
    assert g.comp_best.effective_cost == pytest.approx(49050 / 95, rel=1e-3)
    assert g.recommended.kind == "compressed"
    assert r.recommendation["strategy"] in ("buy_compressed", "optimal_mix")


def test_gas_decompression_loss_raises_compressed_cost():
    common = dict(
        target="H", basis="sell", needs=[Need(25268, "Fullerite-C50", 0)],
        sources=[Source("jita", "Jita", cost_per_m3=0.0)],
        item_prices={"jita": {25268: 500.0, 62586: 50000.0}},
        volumes={25268: 10.0, 62586: 0.05}, gas_infos=[_gas(100)],
    )
    lo = compare_gas(decompression_loss=0.0, **common).gases[0].comp_best.effective_cost
    hi = compare_gas(decompression_loss=0.20, **common).gases[0].comp_best.effective_cost
    assert lo == pytest.approx(500.0)
    assert hi == pytest.approx(50000 / 80)
    assert hi > lo


def test_gas_no_compression_data_skips_compressed_path():
    info = GasInfo(reg_type_id=25268, reg_name="Fullerite-C50", reg_volume=10.0,
                   comp_type_id=None, comp_name=None, comp_volume=None,
                   units_per_compressed=None)
    r = compare_gas(
        target="H", basis="sell", needs=[Need(25268, "Fullerite-C50", 100)],
        sources=[Source("jita", "Jita", cost_per_m3=0.0)],
        item_prices={"jita": {25268: 500.0}}, volumes={25268: 10.0},
        gas_infos=[info], decompression_loss=0.05,
    )
    g = r.gases[0]
    assert g.comp_best is None
    assert g.recommended.kind == "regular"
    comp_strat = next(s for s in r.strategies if s.strategy == "buy_compressed")
    assert "Fullerite-C50" in comp_strat.missing
