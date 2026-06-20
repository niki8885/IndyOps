"""
Native Haskell invention optimizer (haskell/invention-optimizer) behind a thin
adapter, mirroring app.adapters.risk_engine / chain_engine.

The Python core (app.services.invention_opt.optimize) is the oracle; this adapter
prefers the native binary and falls back to Python on any failure. The binary is a
pure stdin→stdout JSON filter: products + decryptors (+ optional weights) in, the
ranked (product × decryptor) candidates out.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from app.services import invention_opt as core
from app.services.invention import Decryptor
from app.services.invention_opt import OptInput

logger = logging.getLogger(__name__)
_BIN_NAME = "invention-optimizer.exe" if os.name == "nt" else "invention-optimizer"


def _default_binary() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "haskell" / "invention-optimizer" / "bin" / _BIN_NAME


def binary_path() -> Path:
    env = os.environ.get("INVENTION_OPTIMIZER_BIN")
    return Path(env) if env else _default_binary()


def available() -> bool:
    return binary_path().is_file()


def _request(products: list[OptInput], decryptors: list[Decryptor],
             decryptor_prices: dict[int, float], weights: Optional[dict[str, float]]) -> dict:
    req: dict = {
        "products": [
            {
                "product_type_id": p.product_type_id,
                "product_name": p.product_name,
                "base_prob": p.base_prob,
                "base_runs": p.base_runs,
                "units_per_run": p.units_per_run,
                "datacore_cost": p.datacore_cost,
                "invention_install": p.invention_install_cost,
                "manuf_install_per_run": p.manuf_install_per_run,
                "sell_per_unit": p.sell_per_unit,
                "materials": [{"qty": m.qty, "price": m.price} for m in p.materials],
                "mat_extra_mult": p.mat_extra_mult,
                "encryption": p.encryption, "sci1": p.sci1, "sci2": p.sci2,
            }
            for p in products
        ],
        "decryptors": [
            {
                "name": d.name, "prob_mod": d.prob_mod, "me_mod": d.me_mod,
                "te_mod": d.te_mod, "runs_mod": d.runs_mod,
                "price": (decryptor_prices.get(d.type_id, 0.0) if d.type_id else 0.0),
            }
            for d in decryptors
        ],
    }
    if weights:
        req["weights"] = weights
    return req


def optimize_native(products: list[OptInput], decryptors: list[Decryptor],
                    decryptor_prices: dict[int, float],
                    weights: Optional[dict[str, float]] = None,
                    *, timeout: float = 30.0) -> list[dict]:
    """Run the Haskell binary. Raises if it is missing or fails."""
    path = binary_path()
    if not path.is_file():
        raise FileNotFoundError(f"invention-optimizer binary not found at {path}")
    req = _request(products, decryptors, decryptor_prices, weights)
    proc = subprocess.run(
        [str(path)], input=json.dumps(req, allow_nan=False),
        capture_output=True, text=True, encoding="utf-8", timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"invention-optimizer exit {proc.returncode}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)["ranked"]


def optimize(products: list[OptInput], decryptors: list[Decryptor],
             decryptor_prices: dict[int, float],
             weights: Optional[dict[str, float]] = None,
             *, prefer_native: bool = True, timeout: float = 30.0) -> tuple[list[dict], str]:
    """Return ``(ranked, engine)`` where engine is "haskell" or "python". Prefers the
    native binary; falls back to the Python oracle on any failure."""
    if prefer_native and available():
        try:
            return optimize_native(products, decryptors, decryptor_prices, weights, timeout=timeout), "haskell"
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("invention-optimizer native failed, falling back to Python: %s", exc)
    return core.optimize(products, decryptors, decryptor_prices, weights), "python"
