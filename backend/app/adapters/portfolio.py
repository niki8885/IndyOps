"""
Adapter for the native ``portfolio-opt`` Markowitz optimiser (4th Fortran binary
in ``fortran/analytics-engine``). Prefers the native engine, falls back to the pure
Python oracle (``services.portfolio``) on any failure — mirrors
``adapters/profit_sim.py`` / ``adapters/scenario_sim.py``.

The optimisation is deterministic (water-filling on a diagonal-Sigma simplex), so
native and oracle agree to numerical precision (see ``test_portfolio_fortran_parity``).
"""
from __future__ import annotations
import json
import logging
import os
import subprocess
from pathlib import Path

from app.services import portfolio as core

logger = logging.getLogger(__name__)
_BIN_NAME = "portfolio-opt.exe" if os.name == "nt" else "portfolio-opt"


def _default_binary() -> Path:
    # backend/app/adapters/portfolio.py → repo root is parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "fortran" / "analytics-engine" / "bin" / _BIN_NAME


def binary_path() -> Path:
    env = os.environ.get("PORTFOLIO_OPT_BIN")
    return Path(env) if env else _default_binary()


def available() -> bool:
    return binary_path().is_file()


def _native(mu, sigma, risk_aversion: float, timeout: float) -> tuple[list[float], dict]:
    path = binary_path()
    payload = json.dumps(
        {"n": len(mu), "risk_aversion": float(risk_aversion),
         "mu": [float(x) for x in mu], "sigma": [float(x) for x in sigma]},
        allow_nan=False,
    )
    proc = subprocess.run(
        [str(path)], input=payload, capture_output=True, text=True,
        encoding="utf-8", timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"portfolio-opt exit {proc.returncode}: {proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    metrics = {"exp_return": data["exp_return"], "variance": data["variance"], "stddev": data["stddev"]}
    return data["weights"], metrics


def optimize_weights(mu, sigma, risk_aversion: float, *,
                     prefer_native: bool = True, timeout: float = 30.0) -> tuple[list[float], dict, str]:
    """Return ``(weights, metrics, engine)`` where engine is "fortran" or "python"."""
    mu = list(mu)
    if not mu:
        return [], {"exp_return": 0.0, "variance": 0.0, "stddev": 0.0}, "python"
    if prefer_native and available():
        try:
            w, m = _native(mu, sigma, risk_aversion, timeout)
            return w, m, "fortran"
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("portfolio-opt native compute failed, falling back to Python: %s", exc)
    w, m = core.optimize(mu, sigma, risk_aversion)
    return w, m, "python"
