"""Pure research-math tests: ME savings + payback, research time/cost, copying.
No DB/web — imports only app.services.research."""
from app.services import research as r


def test_me_no_effect_on_qty_one():
    # base qty 1: −10% still ceils to 1, so ME research saves nothing for it.
    mats = [{"type_id": 1, "name": "TinyPart", "base_qty": 1, "unit_price": 1000.0}]
    rows, saved = r.me_material_savings(mats, from_me=0, to_me=10)
    assert rows[0]["qty_from"] == 1 and rows[0]["qty_to"] == 1
    assert rows[0]["me_no_effect"] is True
    assert saved == 0.0


def test_me_savings_and_payback():
    mats = [{"type_id": 34, "name": "Tritanium", "base_qty": 1000, "unit_price": 5.0}]
    rows, saved = r.me_material_savings(mats, from_me=0, to_me=10)
    # 1000 → ceil(900) = 900 → 100 units saved × 5 ISK = 500/run
    assert rows[0]["saved_units"] == 100
    assert saved == 500.0
    assert rows[0]["me_no_effect"] is False
    # cost 1,000,000 / 500 per-run = 2000 runs to break even
    assert r.payback_runs(1_000_000, saved) == 2000.0
    assert r.payback_runs(1_000_000, 0) is None  # never pays back


def test_research_time_scales_with_levels_and_skills():
    # rank-1 blueprint: base research time = level-1 seconds (105). The table is
    # cumulative, so reaching a level costs that level's value (not the sum).
    assert r.research_time(105, 0, 1, time_mult=1.0) == 105      # reach ME1 = 105 s
    assert r.research_time(105, 0, 4, time_mult=1.0) == 1414     # reach ME4 = 24 m (EVE Uni)
    full = r.research_time(105, 0, 10, time_mult=1.0)
    assert full == r.RESEARCH_LEVEL_SECONDS[10]                  # reach ME10 = 256,000 s (~3 days)
    # a partial span is the difference of the cumulative endpoints
    assert r.research_time(105, 4, 7, time_mult=1.0) == r.RESEARCH_LEVEL_SECONDS[7] - r.RESEARCH_LEVEL_SECONDS[4]
    # Advanced Industry V (×0.85) shortens it; no-op span is zero.
    assert r.research_time(105, 0, 10, time_mult=0.85) < full
    assert r.research_time(105, 5, 5, time_mult=1.0) == 0


def test_research_cost_breakdown():
    jc = r.research_cost(manuf_eiv_1run=1_000_000.0, from_lvl=0, to_lvl=1,
                         index=0.05, cost_role_pct=0.0, facility_tax_pct=0.0)
    # base = EIV × 0.02 × ratio(0→1=1) = 20,000; system = ×0.05 = 1,000; +SCC 4% of base = 800
    assert jc.base_cost == 20000.0
    assert jc.system_cost == 1000.0
    assert jc.scc_surcharge == 800.0
    assert jc.install_cost == 1800.0


def test_te_time_saving_and_payback():
    # base manuf time 1000s/run: TE0 → 1000, TE20 → 800 → 200s saved/run.
    saved = r.te_time_saving_per_run(1000, from_te=0, to_te=20)
    assert saved == 200
    assert r.time_payback_runs(40000, saved) == 200.0


def test_copy_plan():
    plan = r.copy_plan(base_copy_time_per_run=100, manuf_eiv_1run=1_000_000.0,
                       runs_per_copy=10, copies=2, copy_index=0.05)
    assert plan["total_runs"] == 20
    assert plan["time_s"] == 2000
    # base = 1e6 × 0.02 × 20 = 400,000 → system = ×0.05 = 20,000
    assert plan["cost"]["base_cost"] == 400000.0
    assert plan["cost"]["system_cost"] == 20000.0
