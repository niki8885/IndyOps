"""
Native Fortran analytics engine (fortran/analytics-engine) behind a thin adapter,
mirroring app.adapters.chain_engine.

The Python core (app.services.index_report.compute_index_payload) stays as the
oracle; this adapter prefers the native binary and falls back to Python on any
failure, so the app works whether or not the engine is built. The binary is a
pure stdin→stdout JSON filter: it receives a numeric-only request (datetime is
decoded here into weekday/hour and a last-24h mask) and returns the computed
series/stats/risk/montecarlo/heatmap/states, which we re-wrap into the exact same
payload shape the oracle produces (pass-through key/label/kind/window/timestamps/
price/volume are re-attached here).
"""
from __future__ import annotations
import json
import logging
import os
import subprocess
from pathlib import Path

import pandas as pd

from app.services import index_report
from app.services._numeric import series

logger = logging.getLogger(__name__)
_BIN_NAME = "analytics-engine.exe" if os.name == "nt" else "analytics-engine"

# Monte-Carlo / risk parameters — must match the Python oracle's defaults
# (risk.monte_carlo_gbm: horizon=24, n_paths=500, seed=42).
_MC = {"horizon": 24, "n_paths": 500, "seed": 42}


def _default_binary() -> Path:
    # backend/app/adapters/analytics_engine.py → repo root is four parents up
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "fortran" / "analytics-engine" / "bin" / _BIN_NAME


def binary_path() -> Path:
    env = os.environ.get("ANALYTICS_ENGINE_BIN")
    return Path(env) if env else _default_binary()


def available() -> bool:
    return binary_path().is_file()


def _num_list(s: pd.Series) -> list:
    """Floats with NaN→None, so json.dumps emits `null` (not the `NaN` token)."""
    return [None if pd.isna(v) else float(v) for v in s]


def _last_or_none(s: pd.Series):
    v = s.iloc[-1]
    return None if pd.isna(v) else float(v)


def build_request(df: pd.DataFrame, window: int) -> dict:
    """Numeric-only request for the engine. Calendar fields (weekday/hour/last-24h
    mask) are decoded here — that is parsing, not financial compute."""
    ts = df["timestamp"]
    cutoff = ts.max() - pd.Timedelta(hours=24)
    return {
        "window": max(2, int(window)),
        "price": _num_list(df["price"].astype(float)),
        "volume": _num_list(df["volume"]),
        "last24_mask": [1 if t >= cutoff else 0 for t in ts],
        "weekday": [int(t.weekday()) for t in ts],
        "hour": [int(t.hour) for t in ts],
        "liquidity_last": _last_or_none(df["liquidity"]),
        "entropy_last": _last_or_none(df["entropy"]),
        "top3_share_last": _last_or_none(df["top3_share"]),
        "mc": dict(_MC),
    }


def _wrap(df: pd.DataFrame, key: str, label: str, kind: str, win: int, computed: dict) -> dict:
    """Assemble the full index payload (identical shape to the oracle), attaching
    pass-through fields the engine doesn't need to compute."""
    series_out = {"price": series(df["price"].astype(float)), "volume": series(df["volume"])}
    series_out.update(computed["series"])
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "window": win,
        "timestamps": [t.isoformat() for t in df["timestamp"]],
        "series": series_out,
        "stats": computed["stats"],
        "risk": computed["risk"],
        "montecarlo": computed["montecarlo"],
        "heatmap": computed["heatmap"],
        "states": computed["states"],
    }


def compute_native(df: pd.DataFrame, key: str, label: str, kind: str, window: int,
                   *, timeout: float = 30.0) -> dict:
    """Run the Fortran binary. Raises if it is missing or fails."""
    path = binary_path()
    if not path.is_file():
        raise FileNotFoundError(f"analytics-engine binary not found at {path}")
    win = max(2, int(window))
    payload_in = json.dumps(build_request(df, win), allow_nan=False)
    proc = subprocess.run(
        [str(path)], input=payload_in, capture_output=True, text=True,
        encoding="utf-8", timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"analytics-engine exit {proc.returncode}: {proc.stderr.strip()}")
    return _wrap(df, key, label, kind, win, json.loads(proc.stdout))


def compute(df: pd.DataFrame, key: str, label: str, kind: str, window: int,
            *, prefer_native: bool = True, timeout: float = 30.0) -> tuple[dict, str]:
    """
    Return ``(payload, engine)`` where engine is "fortran" or "python". Prefers the
    native binary; falls back to the Python oracle on any failure.
    """
    if prefer_native and available():
        try:
            return compute_native(df, key, label, kind, window, timeout=timeout), "fortran"
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("analytics-engine native compute failed, falling back to Python: %s", exc)
    return index_report.compute_index_payload(df, key, label, kind, window), "python"
