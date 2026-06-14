"""
Shared numeric helpers for the pure service layer.

JSON-safety + numpy→python coercion lived duplicated in analysis_router
(``_clean``/``_series``) and tracking_router (``_clean``/``_ser``). This is the
single source of truth. No SQLAlchemy / FastAPI / requests here — numbers only.
"""
from __future__ import annotations

import math

import numpy as np


def clean(x):
    """JSON-safe scalar: NaN/inf → None, numpy scalar → python scalar."""
    if x is None:
        return None
    if isinstance(x, (np.floating, float)):
        return None if (math.isnan(x) or math.isinf(x)) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    return x


def series(s) -> list:
    """Clean a pandas Series (or anything with ``.tolist()``) to a JSON-safe list."""
    return [clean(v) for v in s.tolist()]
