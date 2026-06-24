"""
Native forecast-engine (fortran/analytics-engine → forecast-engine binary) behind
a thin adapter, mirroring app.adapters.demand_engine.

The Python core (app.services.forecast) is the **oracle**; this adapter prefers the
native binary and falls back to Python on any failure. The engine does the heavy
half only — the per-target model panel (fit + walk-forward backtest + P10/P50/P90
bands) for volume and price; the trivial glue (future dates, ISK turnover, signal)
stays in Python via forecast.assemble, so the payload is identical either way.

Wire format is numeric-only: Python cleans the series (missing volume → 0, price
interpolated) and the engine returns {volume:{…}, price:{…}}.
"""
from __future__ import annotations
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

import pandas as pd

from app.services import forecast as forecast_oracle
from app.services.forecast import SEASON
from app.services.market_browser import _history_frame

logger = logging.getLogger(__name__)
_BIN_NAME = "forecast-engine.exe" if os.name == "nt" else "forecast-engine"


def _default_binary() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "fortran" / "analytics-engine" / "bin" / _BIN_NAME


def binary_path() -> Path:
    env = os.environ.get("FORECAST_ENGINE_BIN")
    return Path(env) if env else _default_binary()


def available() -> bool:
    return binary_path().is_file()


def _num_list(a) -> list:
    return [None if pd.isna(v) else float(v) for v in a]


def build_request(vol, price, h: int) -> dict:
    return {"price": _num_list(price), "volume": _num_list(vol),
            "horizon": int(h), "season": SEASON}


def compute_native(history: list[dict], type_id: int, label: str,
                   region_name: Optional[str], horizon: int,
                   *, timeout: float = 60.0) -> dict:
    """Run the Fortran binary for the panel forecast, assemble the payload in Python."""
    path = binary_path()
    if not path.is_file():
        raise FileNotFoundError(f"forecast-engine binary not found at {path}")
    h = max(1, int(horizon))
    df = _history_frame(history)
    vol, price = forecast_oracle.clean_series(df)
    payload_in = json.dumps(build_request(vol, price, h), allow_nan=False)
    proc = subprocess.run(
        [str(path)], input=payload_in, capture_output=True, text=True,
        encoding="utf-8", timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"forecast-engine exit {proc.returncode}: {proc.stderr.strip()}")
    computed = json.loads(proc.stdout)
    return forecast_oracle.assemble(df, type_id, label, region_name, h, vol, price,
                                    computed["volume"], computed["price"])


def compute(history: list[dict], type_id: int, label: str,
            region_name: Optional[str], horizon: int,
            *, prefer_native: bool = True, timeout: float = 60.0) -> tuple[dict, str]:
    """Return ``(payload, engine)`` — prefers the native binary, falls back to Python."""
    if prefer_native and available():
        try:
            return compute_native(history, type_id, label, region_name, horizon,
                                  timeout=timeout), "fortran"
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("forecast-engine native compute failed, falling back to Python: %s", exc)
    return forecast_oracle.forecast_payload(history, type_id, label, region_name, horizon), "python"
