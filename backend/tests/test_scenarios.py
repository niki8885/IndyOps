"""
IO-23 pure scenario layer: catalog coverage, the ``apply`` transform (price /
volatility / volume / tax / slots / time shifts), ``compose`` (composite stress
tests), and ``compare`` (profit / risk / ROI diff vs baseline).
"""
import math

from app.services import profit_sim as ps
from app.services import scenarios as sc


def _req():
    hist = {
        2: ps.TypeHistory(buy=[95, 100, 105, 98, 102, 110, 90, 99],
                          sell=[100, 106, 110, 103, 108, 116, 95, 104],
                          volume=[80000] * 8, last_buy=100, anchor_buy=100),
        1: ps.TypeHistory(buy=[4800, 5000, 5200, 4900],
                          sell=[5000, 5200, 5400, 5100, 4950, 5300, 5150, 5250],
                          volume=[400] * 8, last_sell=5000, anchor_sell=5000),
    }
    params = ps.SimParams(n_iterations=2000, seed=3)
    return ps.request_from_legs("t", [(2, 10)], 1, 5, hist, 100.0, 600, params,
                                broker_fee_pct=3.6, sales_tax_pct=2.0)


def test_catalog_covers_all_categories_and_min_count():
    cat = sc.catalog()
    assert len(cat) >= 12
    cats = {s.category for s in cat}
    assert {sc.EXOGENOUS, sc.LOGISTICS, sc.DEMAND, sc.COUNTERFACTUAL, sc.ENDOGENOUS} <= cats
    # keys unique, names non-empty
    assert len({s.key for s in cat}) == len(cat)
    assert all(s.name and s.description for s in cat)


def test_apply_identity_is_noop():
    req = _req()
    out = sc.apply(req, sc.ScenarioParams())
    assert out.fixed_cost == req.fixed_cost
    assert out.production_time_s == req.production_time_s
    assert out.params.slots == req.params.slots
    assert out.product.broker_fee_pct == req.product.broker_fee_pct
    assert out.legs[0].qgrid == req.legs[0].qgrid
    assert math.isclose(out.legs[0].mu, req.legs[0].mu)


def test_apply_price_and_volatility_shifts():
    req = _req()
    out = sc.apply(req, sc.ScenarioParams(material_price_mult=2.0, product_price_mult=0.5,
                                          volatility_mult=1.5))
    # material grid doubles, product grid halves
    assert math.isclose(out.legs[0].qgrid[50], req.legs[0].qgrid[50] * 2.0)
    assert math.isclose(out.product.qgrid[50], req.product.qgrid[50] * 0.5)
    # log-level shifts by log(mult), preserving path anchors
    assert math.isclose(out.legs[0].mu, req.legs[0].mu + math.log(2.0))
    assert math.isclose(out.legs[0].x0, req.legs[0].x0 + math.log(2.0))
    assert math.isclose(out.product.mu, req.product.mu + math.log(0.5))
    # volatility scales σ and per-step σ
    assert math.isclose(out.legs[0].sigma, req.legs[0].sigma * 1.5)
    assert math.isclose(out.product.step_sigma, req.product.step_sigma * 1.5)


def test_apply_tax_cost_time_slots():
    req = _req()
    out = sc.apply(req, sc.ScenarioParams(tax_mult=1.5, broker_fee_add=1.0, sales_tax_add=0.5,
                                          production_cost_mult=2.0, time_mult=1.5,
                                          slots_mult=2.0, volume_mult=0.5))
    assert math.isclose(out.product.broker_fee_pct, req.product.broker_fee_pct * 1.5 + 1.0)
    assert math.isclose(out.product.sales_tax_pct, req.product.sales_tax_pct * 1.5 + 0.5)
    assert math.isclose(out.fixed_cost, req.fixed_cost * 2.0)
    assert out.production_time_s == int(round(req.production_time_s * 1.5))
    assert out.params.slots == max(1, req.params.slots * 2)
    assert math.isclose(out.legs[0].vol_mean, req.legs[0].vol_mean * 0.5)


def test_apply_logistics_overrides():
    req = _req()
    out = sc.apply(req, sc.ScenarioParams(haul_delay_prob=0.6, haul_delay_hours_mean=48.0,
                                          shortfall_premium_add=0.2, holding_rate_add=0.001))
    assert out.params.haul_delay_prob == 0.6
    assert out.params.haul_delay_hours_mean == 48.0
    assert math.isclose(out.params.shortfall_premium, req.params.shortfall_premium + 0.2)
    assert math.isclose(out.params.holding_daily_rate, req.params.holding_daily_rate + 0.001)


def test_compose_multiplies_and_adds():
    a = sc.ScenarioParams(material_price_mult=1.2, sales_tax_add=1.0, haul_delay_prob=0.4)
    b = sc.ScenarioParams(material_price_mult=1.5, sales_tax_add=0.5, haul_delay_prob=0.7,
                          volatility_mult=2.0)
    comp = sc.compose([a, b])
    assert math.isclose(comp.material_price_mult, 1.2 * 1.5)
    assert math.isclose(comp.sales_tax_add, 1.5)
    assert math.isclose(comp.volatility_mult, 2.0)
    assert comp.haul_delay_prob == 0.7  # worst-case (max) override


def test_composite_scenario_builds_and_skips_unknown():
    comp = sc.composite_scenario(["market_shock_up", "resource_shortage", "does_not_exist"])
    assert comp is not None and comp.category == sc.COMPOSITE
    # product of the two known scenarios' material multipliers
    expect = (sc.SCENARIOS["market_shock_up"].params.material_price_mult
              * sc.SCENARIOS["resource_shortage"].params.material_price_mult)
    assert math.isclose(comp.params.material_price_mult, expect)
    assert sc.composite_scenario(["nope"]) is None


def test_compare_signs_and_viability():
    base = {"expected_profit": 1000.0, "std": 200.0, "var5": -50.0, "prob_loss": 0.1,
            "breakdown": {"material_cost": {"mean": 4000.0}}}
    worse = {"expected_profit": -100.0, "std": 600.0, "var5": -900.0, "prob_loss": 0.7,
             "breakdown": {"material_cost": {"mean": 5000.0}}}
    cmp = sc.compare(base, worse, base_fixed_cost=100.0, scen_fixed_cost=130.0)
    assert cmp.abs_profit_change == -1100.0
    assert cmp.pct_profit_change < 0
    assert cmp.std_change > 0 and cmp.var5_change < 0
    assert cmp.prob_loss_change > 0
    assert cmp.roi_baseline > 0 and cmp.roi_scenario < 0
    assert cmp.viable is False


def test_simulate_oracle_baseline_matches_direct():
    req = _req()
    specs = [sc.SCENARIOS["jita_plus_20"].params, sc.SCENARIOS["taxes_half"].params]
    base, scen = sc.simulate_oracle(req, specs)
    direct = ps.simulate(req).metrics
    assert math.isclose(base.expected_profit, direct.expected_profit)
    assert len(scen) == 2
    # +20% on the product price must raise expected profit vs baseline
    assert scen[0].expected_profit > base.expected_profit
