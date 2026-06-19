"""
Parity: the native scenario engine (fortran/analytics-engine → scenario-sim) must agree
with the Python oracle (services.scenarios.simulate_oracle) on the baseline AND on every
scenario. Statistical, not bit-exact (separate seed-deterministic RNGs), like the
profit-sim parity test. Auto-skipped where the binary isn't built (SCENARIO_SIM_BIN or
the default fortran/analytics-engine/bin/scenario-sim[.exe]).
"""
import pytest

from app.adapters import scenario_sim as eng
from app.services import profit_sim as ps
from app.services import scenarios as sc

pytestmark = pytest.mark.skipif(not eng.available(),
                                reason="scenario-sim binary not built on this host")

REL = 0.06
ABS_P = 0.03

_HIST = {
    1: ps.TypeHistory(buy=[95, 100, 105, 98, 102, 110, 90, 99, 101, 108],
                      sell=[100, 106, 110, 103, 108, 116, 95, 104, 107, 114],
                      volume=[8000] * 10, last_buy=100, anchor_buy=100),
    3: ps.TypeHistory(group_id=1, buy=[40, 42, 38, 41, 43, 39, 44],
                      sell=[42, 44, 40, 43, 45, 41, 46], volume=[20000] * 7, last_buy=42),
    2: ps.TypeHistory(group_id=2, buy=[1900, 2000, 2100, 1950, 2050],
                      sell=[1950, 2050, 2150, 2000, 2100], volume=[3000] * 5, last_sell=2050),
}


def _req(**pk):
    params = ps.SimParams(**{"n_iterations": 40_000, "participation_cap": 0.3, "seed": 9, **pk})
    return ps.request_from_legs("parity", [(1, 10), (3, 50)], 2, 5, _HIST,
                                fixed_cost=250.0, production_time_s=7200, params=params,
                                broker_fee_pct=3.6, sales_tax_pct=2.0)


_SPECS = [
    sc.SCENARIOS["market_shock_up"].params,
    sc.SCENARIOS["resource_shortage"].params,
    sc.SCENARIOS["tax_increase"].params,
    sc.SCENARIOS["logistics_disruption"].params,
    sc.SCENARIOS["production_expansion"].params,
    sc.composite_scenario(["market_shock_up", "resource_shortage", "hauling_cost_spike"]).params,
]

_TIGHT = ["expected_profit", "median_profit", "std", "var5", "cvar5"]


def _close(a, b, rel=REL):
    assert abs(a - b) <= rel * (abs(b) + 1.0), f"{a} vs {b}"


@pytest.mark.parametrize("pk", [
    {"dist_mode": 0, "corr_mode": 0},
    {"dist_mode": 1, "corr_mode": 0},
    {"dist_mode": 0, "corr_mode": 0, "copula": 1, "t_df": 5.0},
    {"dist_mode": 0, "corr_mode": 0, "path_steps": 24, "garch": 1},
])
def test_native_matches_oracle(pk):
    req = _req(**pk)
    base_n, scen_n, engine = eng.simulate(req, _SPECS, prefer_native=True)
    base_o, scen_o = sc.simulate_oracle(req, _SPECS)
    assert engine == "fortran"
    assert len(scen_n) == len(scen_o) == len(_SPECS)

    for k in _TIGHT:
        _close(getattr(base_n, k), getattr(base_o, k))
    assert abs(base_n.prob_loss - base_o.prob_loss) <= ABS_P

    for sn, so in zip(scen_n, scen_o):
        for k in _TIGHT:
            _close(getattr(sn, k), getattr(so, k))
        assert abs(sn.prob_loss - so.prob_loss) <= ABS_P
        assert set(sn.breakdown) == {"material_cost", "revenue", "taxes_fees", "logistics"}
        _close(sn.breakdown["material_cost"]["mean"], so.breakdown["material_cost"]["mean"])
        assert len(sn.hist_counts) == 40 and sum(sn.hist_counts) == req.params.n_iterations
