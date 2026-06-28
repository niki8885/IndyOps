"""
Native Haskell Reaction Planner batch engine (haskell/chain-engine ``reaction-planner``
executable) behind a thin adapter, mirroring app.adapters.chain_engine /
app.adapters.risk_engine.

The Python core (app.services.reaction_planner) stays the oracle; this adapter prefers
the native binary and falls back to Python on any failure. The binary is a pure
stdin→stdout JSON filter: it receives the candidate set (+ slot counts) and returns the
ROI-ranked per-candidate metrics.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from app.services import reaction_planner as core
from app.services.reaction_planner import Candidate, CandidateResult

logger = logging.getLogger(__name__)
_BIN_NAME = "reaction-planner.exe" if os.name == "nt" else "reaction-planner"


def _default_binary() -> Path:
    # backend/app/adapters/reaction_planner_engine.py → repo root is four parents up.
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "haskell" / "chain-engine" / "bin" / _BIN_NAME


def binary_path() -> Path:
    env = os.environ.get("REACTION_PLANNER_BIN")
    return Path(env) if env else _default_binary()


def available() -> bool:
    return binary_path().is_file()


def analyze_native(cands: list[Candidate], man_slots: int, react_slots: int,
                   *, timeout: float = 60.0) -> list[CandidateResult]:
    """Run the Haskell binary. Raises if it is missing or fails."""
    path = binary_path()
    if not path.is_file():
        raise FileNotFoundError(f"reaction-planner binary not found at {path}")
    payload = json.dumps(core.to_request_dict(cands, man_slots, react_slots))
    proc = subprocess.run(
        [str(path)], input=payload, capture_output=True, text=True,
        encoding="utf-8", timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"reaction-planner exit {proc.returncode}: {proc.stderr.strip()}")
    return core.results_from_dict(json.loads(proc.stdout))


def analyze(cands: list[Candidate], man_slots: int, react_slots: int,
            *, prefer_native: bool = True, timeout: float = 60.0) -> tuple[list[CandidateResult], str]:
    """Return ``(results, engine)`` where engine is "haskell" or "python". Prefers the
    native binary; falls back to the Python oracle on any failure."""
    if prefer_native and available():
        try:
            return analyze_native(cands, man_slots, react_slots, timeout=timeout), "haskell"
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("reaction-planner native analyze failed, falling back to Python: %s", exc)
    return core.analyze_candidates(cands, man_slots, react_slots), "python"
