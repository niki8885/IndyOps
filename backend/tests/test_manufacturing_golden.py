"""
Golden tests: known recipes through run_calculation, profit/margin locked to
the ISK. Expected values are hand-computed (not produced by the code) so a
formula regression is caught.
"""
import pytest
from app.services.manufacturing import CalcInput, Material, run_calculation


def _calc(**kw):
    base = dict(
        product_name="X", product_qty_per_run=1, runs=1, me=0, te=0, base_time_per_run=600,
        materials=[], output_price=0.0, bpc_cost=0.0, broker_fee_pct=0.0,
        system_cost_index=0.0, facility_tax_pct=0.0,
    )
    base.update(kw)
    return run_calculation(CalcInput(**base))


def test_golden_a_basic():
    # ME0, no fees/index: only the fixed 4% SCC surcharge hits install.
    # mats 100×5 + 40×10 = 900; eiv→900; scc 36; sell 2000; profit 1064.
    r = _calc(
        materials=[Material(34, "Tritanium", 100, 5.0), Material(35, "Pyerite", 40, 10.0)],
        output_price=2000.0,
    )
    assert r.materials_total_gross == pytest.approx(900.0)
    assert r.job_cost.scc_surcharge == pytest.approx(36.0)
    assert r.job_cost.net_install_cost == pytest.approx(36.0)
    assert r.output.net_sell == pytest.approx(2000.0)
    assert r.results.total_costs == pytest.approx(936.0)
    assert r.results.profit == pytest.approx(1064.0)
    assert r.results.margin_pct == pytest.approx(113.68)


def test_golden_b_me_windows_eiv_fees():
    # ME10 on 100 → 180/job; ×2 windows = 360 units ×5 = 1800 mat.
    # EIV 500 single-job ×2 windows = 1000 → sci 50 + tax 10 + scc 40 = 100 install.
    # bpc 100 ×2 = 200; sell 4×1000×0.95 = 3800; costs 2100; profit 1700.
    r = _calc(
        runs=2, windows=2, me=10,
        materials=[Material(34, "Tritanium", 100, 5.0)],
        output_price=1000.0, broker_fee_pct=5.0, bpc_cost=100.0,
        estimated_item_value=500.0, system_cost_index=0.05, facility_tax_pct=1.0,
    )
    assert r.output.quantity == 4
    assert r.materials_total_gross == pytest.approx(1800.0)
    assert r.bpc_cost == pytest.approx(200.0)
    assert r.job_cost.estimated_item_value == pytest.approx(1000.0)
    assert r.job_cost.net_install_cost == pytest.approx(100.0)
    assert r.results.total_costs == pytest.approx(2100.0)
    assert r.results.profit == pytest.approx(1700.0)
    assert r.results.margin_pct == pytest.approx(80.95)


def test_golden_c_stacking_bonuses():
    # rig ME 2% and structure-role ME 1% stack multiplicatively:
    # 1000 × 0.98 × 0.99 = 970.2 → ceil 971 (saved 29). scc 38.84; profit 990.16.
    r = _calc(
        materials=[Material(34, "Tritanium", 1000, 1.0)],
        output_price=2000.0, material_bonus_pct=2.0, material_role_pct=1.0,
    )
    mat = r.materials[0]
    assert mat.adj_qty == 971
    assert mat.saved == 29
    assert r.job_cost.scc_surcharge == pytest.approx(38.84)
    assert r.results.total_costs == pytest.approx(1009.84)
    assert r.results.profit == pytest.approx(990.16)
    assert r.results.margin_pct == pytest.approx(98.05)
