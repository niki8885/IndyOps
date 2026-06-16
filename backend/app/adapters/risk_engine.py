"""
Native Haskell risk-scoring & strategy-ranking engine (haskell/risk-engine) behind
a thin adapter, mirroring app.adapters.chain_engine.

The Python core (app.services.profit_sim.rank_strategies) stays as the oracle; this
adapter prefers the native binary and falls back to Python on any failure. The
binary is a pure stdin→stdout JSON filter: it receives the candidate strategies'
ranking metrics (+ optional weight overrides) and returns the ranked list.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from app.services import profit_sim as core
from app.services.profit_sim import RankInput, RankedStrategy

logger = logging.getLogger(__name__)
_BIN_NAME = "risk-engine.exe" if os.name == "nt" else "risk-engine"


def _default_binary() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "haskell" / "risk-engine" / "bin" / _BIN_NAME


def binary_path() -> Path:
    env = os.environ.get("RISK_ENGINE_BIN")
    return Path(env) if env else _default_binary()


def available() -> bool:
    return binary_path().is_file()


def _request(items: list[RankInput], weights: Optional[dict[str, float]]) -> dict:
    req: dict = {"strategies": [asdict(it) for it in items]}
    if weights:
        req["weights"] = weights
    return req


def rank_native(items: list[RankInput], weights: Optional[dict[str, float]] = None,
                *, timeout: float = 30.0) -> list[RankedStrategy]:
    """Run the Haskell binary. Raises if it is missing or fails."""
    path = binary_path()
    if not path.is_file():
        raise FileNotFoundError(f"risk-engine binary not found at {path}")
    proc = subprocess.run(
        [str(path)], input=json.dumps(_request(items, weights), allow_nan=False),
        capture_output=True, text=True, encoding="utf-8", timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"risk-engine exit {proc.returncode}: {proc.stderr.strip()}")
    out = json.loads(proc.stdout)
    return [RankedStrategy(rank=r["rank"], label=r["label"], score=r["score"])
            for r in out["ranked"]]


def rank(items: list[RankInput], weights: Optional[dict[str, float]] = None,
         *, prefer_native: bool = True, timeout: float = 30.0) -> tuple[list[RankedStrategy], str]:
    """Return ``(ranked, engine)`` where engine is "haskell" or "python". Prefers the
    native binary; falls back to the Python oracle on any failure."""
    if prefer_native and available():
        try:
            return rank_native(items, weights, timeout=timeout), "haskell"
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("risk-engine native rank failed, falling back to Python: %s", exc)
    return core.rank_strategies(items, weights), "python"
