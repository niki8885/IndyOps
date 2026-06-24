"""
Native demand-engine (fortran/analytics-engine → demand-engine binary) behind a
thin adapter, mirroring app.adapters.analytics_engine.

The Python core (app.services.demand.demand_payload) stays as the **oracle**; this
adapter prefers the native binary and falls back to Python on any failure, so the
app works whether or not the engine is built. The binary is a pure stdin→stdout
JSON filter: it receives a numeric-only request (weekday is decoded here, the live
order book is flattened into scalars) and returns the computed series/stats/book/
score, which we re-wrap with the pass-through identity fields (type_id/label/
region_name/timestamps) the adapter already holds.
"""
from __future__ import annotations
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

import pandas as pd

from app.services import demand as demand_oracle
from app.services.market_browser import _history_frame

logger = logging.getLogger(__name__)
_BIN_NAME = "demand-engine.exe" if os.name == "nt" else "demand-engine"


def _default_binary() -> Path:
    # backend/app/adapters/demand_engine.py → repo root is four parents up
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "fortran" / "analytics-engine" / "bin" / _BIN_NAME


def binary_path() -> Path:
    env = os.environ.get("DEMAND_ENGINE_BIN")
    return Path(env) if env else _default_binary()


def available() -> bool:
    return binary_path().is_file()


def _num_list(s: pd.Series) -> list:
    """Floats with NaN→None, so json.dumps emits `null` (not the `NaN` token)."""
    return [None if pd.isna(v) else float(v) for v in s]


def build_request(df: pd.DataFrame, book: Optional[dict]) -> dict:
    """Numeric-only request. Weekday is decoded here (parsing, not compute) and the
    order book is flattened to flat scalars (`src/json.f90` reads only flat keys)."""
    vol = pd.to_numeric(df["volume"], errors="coerce")
    price = df["price"].astype(float)
    oc = pd.to_numeric(df["order_count"], errors="coerce")
    book = book or {}
    return {
        "price": _num_list(price),
        "volume": _num_list(vol),
        "order_count": _num_list(oc),
        "weekday": [int(t.weekday()) for t in df["timestamp"]],
        "book_bid_depth": float(book.get("bid_depth") or 0),
        "book_ask_depth": float(book.get("ask_depth") or 0),
        "book_best_bid": book.get("best_bid"),
        "book_best_ask": book.get("best_ask"),
        "book_spread": book.get("spread"),
        "book_spread_pct": book.get("spread_pct"),
        "book_mid": book.get("mid"),
    }


def _wrap(df: pd.DataFrame, type_id: int, label: str, region_name: Optional[str],
          computed: dict) -> dict:
    """Assemble the full demand payload (identical shape to the oracle), attaching
    the pass-through fields the engine doesn't compute."""
    return {
        "type_id": type_id,
        "label": label,
        "region_name": region_name,
        "timestamps": [t.isoformat() for t in df["timestamp"]],
        "series": computed["series"],
        "stats": computed["stats"],
        "book": computed["book"],
        "weekday_volume": computed["weekday_volume"],
        "weekend_lift": computed["weekend_lift"],
        "weekly_autocorr": computed["weekly_autocorr"],
        "score": computed["score"],
    }


def compute_native(history: list[dict], type_id: int, label: str,
                   region_name: Optional[str], book: Optional[dict],
                   *, timeout: float = 30.0) -> dict:
    """Run the Fortran binary. Raises if it is missing or fails."""
    path = binary_path()
    if not path.is_file():
        raise FileNotFoundError(f"demand-engine binary not found at {path}")
    df = _history_frame(history)
    payload_in = json.dumps(build_request(df, book), allow_nan=False)
    proc = subprocess.run(
        [str(path)], input=payload_in, capture_output=True, text=True,
        encoding="utf-8", timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"demand-engine exit {proc.returncode}: {proc.stderr.strip()}")
    return _wrap(df, type_id, label, region_name, json.loads(proc.stdout))


def compute(history: list[dict], type_id: int, label: str,
            region_name: Optional[str], book: Optional[dict],
            *, prefer_native: bool = True, timeout: float = 30.0) -> tuple[dict, str]:
    """
    Return ``(payload, engine)`` where engine is "fortran" or "python". Prefers the
    native binary; falls back to the Python oracle on any failure.
    """
    if prefer_native and available():
        try:
            return compute_native(history, type_id, label, region_name, book,
                                  timeout=timeout), "fortran"
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("demand-engine native compute failed, falling back to Python: %s", exc)
    return demand_oracle.demand_payload(history, type_id, label, region_name, book), "python"
