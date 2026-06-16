"""
Native Fortran Monte-Carlo profit simulator (fortran/analytics-engine → profit-sim)
behind a thin adapter, mirroring app.adapters.analytics_engine.

The Python core (app.services.profit_sim.simulate) stays as the oracle; this
adapter prefers the native binary and falls back to Python on any failure, so the
app works whether or not the engine is built. The binary is a pure stdin→stdout
JSON filter: it receives the numeric-only, rectangular request built here (2-D
arrays flattened row-major, since the hand-rolled JSON reader only parses flat
arrays) and returns the SimMetrics JSON, which we re-wrap into a SimResult.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import asdict
from pathlib import Path

from app.services import profit_sim as core
from app.services.profit_sim import SimMetrics, SimRequest, SimResult

logger = logging.getLogger(__name__)
_BIN_NAME = "profit-sim.exe" if os.name == "nt" else "profit-sim"


def _default_binary() -> Path:
    # backend/app/adapters/profit_sim.py → repo root is four parents up
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "fortran" / "analytics-engine" / "bin" / _BIN_NAME


def binary_path() -> Path:
    env = os.environ.get("PROFIT_SIM_BIN")
    return Path(env) if env else _default_binary()


def available() -> bool:
    return binary_path().is_file()


def build_request(req: SimRequest) -> dict:
    """Numeric-only, rectangular request for the engine. Per-variable arrays follow
    the var order ``legs…, product`` last; ``qgrid`` / ``L`` / ``loadings`` are
    flattened row-major to match the flat-array JSON reader."""
    p = req.params
    legs = req.legs
    nvars = len(legs) + 1

    def col(attr):  # per-variable column: legs then product
        return [getattr(l, attr) for l in legs] + [getattr(req.product, attr)]

    qgrid_flat: list[float] = []
    for leg in legs:
        qgrid_flat.extend(leg.qgrid)
    qgrid_flat.extend(req.product.qgrid)

    L = req.cholesky_L or [[1.0 if i == j else 0.0 for j in range(nvars)] for i in range(nvars)]
    loadings = req.loadings or [[0.0] for _ in range(nvars)]
    n_factors = len(loadings[0]) if loadings and loadings[0] else 1

    return {
        "n": p.n_iterations, "seed": p.seed, "corr_mode": p.corr_mode, "dist_mode": p.dist_mode,
        "n_legs": len(legs), "n_vars": nvars, "n_factors": n_factors,
        "production_time_s": req.production_time_s, "slots": p.slots,
        "horizon_days": p.horizon_days, "fixed_cost": req.fixed_cost,
        "participation_cap": p.participation_cap, "shortfall_premium": p.shortfall_premium,
        "slippage": p.slippage, "haul_delay_prob": p.haul_delay_prob,
        "haul_delay_hours_mean": p.haul_delay_hours_mean, "holding_daily_rate": p.holding_daily_rate,
        "risk_lambda": p.risk_lambda,
        "broker_fee_pct": req.product.broker_fee_pct, "sales_tax_pct": req.product.sales_tax_pct,
        "product_qty": req.product.qty,
        "qty": [float(l.qty) for l in legs],
        "mu": col("mu"), "sigma": col("sigma"),
        "vol_mean": col("vol_mean"), "vol_sigma": col("vol_sigma"),
        "spread_mean": col("spread_mean"), "spread_sigma": col("spread_sigma"),
        "idio_sigma": req.idio_sigma or [0.0] * nvars,
        "factor_sigma": req.factor_sigma or [1.0] * n_factors,
        "qgrid": qgrid_flat,
        "l": [x for row in L for x in row],
        "loadings": [x for row in loadings for x in row],
    }


def compute_native(req: SimRequest, *, timeout: float = 60.0) -> SimResult:
    """Run the Fortran binary. Raises if it is missing or fails."""
    path = binary_path()
    if not path.is_file():
        raise FileNotFoundError(f"profit-sim binary not found at {path}")
    payload_in = json.dumps(build_request(req), allow_nan=False)
    proc = subprocess.run(
        [str(path)], input=payload_in, capture_output=True, text=True,
        encoding="utf-8", timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"profit-sim exit {proc.returncode}: {proc.stderr.strip()}")
    metrics = SimMetrics(**json.loads(proc.stdout))
    return SimResult(label=req.label, metrics=metrics, engine="fortran")


def simulate(req: SimRequest, *, prefer_native: bool = True, timeout: float = 60.0) -> tuple[SimResult, str]:
    """Return ``(result, engine)`` where engine is "fortran" or "python". Prefers the
    native binary; falls back to the Python oracle on any failure."""
    if prefer_native and available():
        try:
            return compute_native(req, timeout=timeout), "fortran"
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("profit-sim native compute failed, falling back to Python: %s", exc)
    res = core.simulate(req)
    res.engine = "python"
    return res, "python"


# Re-export the metrics as a plain JSON-able dict (API edge convenience).
def metrics_dict(res: SimResult) -> dict:
    return asdict(res.metrics)
