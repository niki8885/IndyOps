"""
Native Scenario Simulation engine (fortran/analytics-engine `scenario-sim`) behind a
thin adapter, mirroring app.adapters.profit_sim.

The pure ``services.scenarios.simulate_oracle`` stays the oracle/fallback; this adapter
prefers the native binary, which runs the baseline + every scenario's Monte-Carlo in a
single process. The wire format is the profit-sim baseline request (see
``app.adapters.profit_sim.build_request``) plus ``n_scenarios`` and one flat ``sc_*``
column per modifier — the hand-rolled Fortran JSON reader only parses flat numeric
arrays, so the scenario *labels/keys* never cross the boundary; the caller re-attaches
them by index. The output is ``{"baseline": SimMetrics, "scenarios": [SimMetrics, …]}``.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from app.adapters import profit_sim as profit_sim_adapter
from app.services import scenarios
from app.services.profit_sim import SimMetrics, SimRequest
from app.services.scenarios import ScenarioParams

logger = logging.getLogger(__name__)
_BIN_NAME = "scenario-sim.exe" if os.name == "nt" else "scenario-sim"


def _default_binary() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "fortran" / "analytics-engine" / "bin" / _BIN_NAME


def binary_path() -> Path:
    env = os.environ.get("SCENARIO_SIM_BIN")
    return Path(env) if env else _default_binary()


def available() -> bool:
    return binary_path().is_file()


def _opt(v) -> float:
    """``None`` → −1.0 sentinel ("no override"), matching the Fortran decode."""
    return -1.0 if v is None else float(v)


def build_request(baseline_req: SimRequest, paramsets: list[ScenarioParams]) -> dict:
    """Baseline profit-sim request + flat scenario modifier columns."""
    req = profit_sim_adapter.build_request(baseline_req)
    req["n_scenarios"] = len(paramsets)
    req["sc_material_price_mult"] = [sp.material_price_mult for sp in paramsets]
    req["sc_product_price_mult"] = [sp.product_price_mult for sp in paramsets]
    req["sc_volatility_mult"] = [sp.volatility_mult for sp in paramsets]
    req["sc_volume_mult"] = [sp.volume_mult for sp in paramsets]
    req["sc_spread_mult"] = [sp.spread_mult for sp in paramsets]
    req["sc_production_cost_mult"] = [sp.production_cost_mult for sp in paramsets]
    req["sc_tax_mult"] = [sp.tax_mult for sp in paramsets]
    req["sc_sales_tax_add"] = [sp.sales_tax_add for sp in paramsets]
    req["sc_broker_fee_add"] = [sp.broker_fee_add for sp in paramsets]
    req["sc_shortfall_premium_add"] = [sp.shortfall_premium_add for sp in paramsets]
    req["sc_holding_rate_add"] = [sp.holding_rate_add for sp in paramsets]
    req["sc_haul_delay_prob"] = [_opt(sp.haul_delay_prob) for sp in paramsets]
    req["sc_haul_delay_hours_mean"] = [_opt(sp.haul_delay_hours_mean) for sp in paramsets]
    req["sc_time_mult"] = [sp.time_mult for sp in paramsets]
    req["sc_slots_mult"] = [sp.slots_mult for sp in paramsets]
    req["sc_horizon_mult"] = [sp.horizon_mult for sp in paramsets]
    return req


def compute_native(baseline_req: SimRequest, paramsets: list[ScenarioParams],
                   *, timeout: float = 120.0) -> tuple[SimMetrics, list[SimMetrics]]:
    path = binary_path()
    if not path.is_file():
        raise FileNotFoundError(f"scenario-sim binary not found at {path}")
    payload_in = json.dumps(build_request(baseline_req, paramsets), allow_nan=False)
    proc = subprocess.run(
        [str(path)], input=payload_in, capture_output=True, text=True,
        encoding="utf-8", timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"scenario-sim exit {proc.returncode}: {proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    base = SimMetrics(**data["baseline"])
    scen = [SimMetrics(**s) for s in data.get("scenarios", [])]
    return base, scen


def simulate(baseline_req: SimRequest, paramsets: list[ScenarioParams],
             *, prefer_native: bool = True,
             timeout: float = 120.0) -> tuple[SimMetrics, list[SimMetrics], str]:
    """Return ``(baseline_metrics, [scenario_metrics], engine)`` where engine is
    "fortran" or "python". Prefers the native binary; falls back to the pure oracle
    on any failure."""
    if prefer_native and available():
        try:
            base, scen = compute_native(baseline_req, paramsets, timeout=timeout)
            return base, scen, "fortran"
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("scenario-sim native compute failed, falling back to Python: %s", exc)
    base, scen = scenarios.simulate_oracle(baseline_req, paramsets)
    return base, scen, "python"
