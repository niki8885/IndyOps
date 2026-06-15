from __future__ import annotations
import json
import logging
import os
import subprocess
from pathlib import Path

from app.services.chain import ChainPlan, ChainRequest, plan_from_dict, solve_chain, to_request_dict

logger = logging.getLogger(__name__)
_BIN_NAME = "chain-engine.exe" if os.name == "nt" else "chain-engine"


def _default_binary() -> Path:
    # backend/app/adapters/chain_engine.py → repo root is four parents up
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "haskell" / "chain-engine" / "bin" / _BIN_NAME


def binary_path() -> Path:
    env = os.environ.get("CHAIN_ENGINE_BIN")
    return Path(env) if env else _default_binary()


def available() -> bool:
    return binary_path().is_file()


def solve_native(req: ChainRequest, *, timeout: float = 30.0) -> ChainPlan:
    """Run the Haskell binary. Raises if it is missing or fails."""
    path = binary_path()
    if not path.is_file():
        raise FileNotFoundError(f"chain-engine binary not found at {path}")
    payload = json.dumps(to_request_dict(req))
    proc = subprocess.run(
        [str(path)], input=payload, capture_output=True, text=True,
        encoding="utf-8", timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"chain-engine exit {proc.returncode}: {proc.stderr.strip()}")
    return plan_from_dict(json.loads(proc.stdout))


def solve(req: ChainRequest, *, prefer_native: bool = True, timeout: float = 30.0) -> tuple[ChainPlan, str]:
    """
    Return ``(plan, engine)`` where engine is "haskell" or "python". Prefers the
    native binary; falls back to the Python core on any failure.
    """
    if prefer_native and available():
        try:
            return solve_native(req, timeout=timeout), "haskell"
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("chain-engine native solve failed, falling back to Python: %s", exc)
    return solve_chain(req), "python"
