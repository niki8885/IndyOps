"""
Pure commodity-index math: basket concentration + liquidity.

Extracted from tasks/update_indices.py (``_concentration``/``_liquidity``).
No I/O — the collector fetches aggregates and stores rows; this only computes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Concentration:
    top3_share: float
    h_index: float      # Herfindahl
    entropy: float


def concentration(weights: list[float]) -> Concentration:
    """Top-3 share, Herfindahl index and Shannon entropy of a basket's weights."""
    ws = [w for w in weights if w > 0]
    total = sum(ws) or 1.0
    norm = [w / total for w in ws]
    top3 = sum(sorted(norm, reverse=True)[:3])
    h = sum(w * w for w in norm)
    entropy = -sum(w * math.log(w) for w in norm if w > 0)
    return Concentration(round(top3, 6), round(h, 6), round(entropy, 6))


def liquidity(volumes: list[float]) -> float | None:
    """Mean/std of basket volumes (a coefficient-of-variation inverse). None if < 2 points."""
    vs = [v for v in volumes if v and v > 0]
    if len(vs) < 2:
        return None
    mean = sum(vs) / len(vs)
    var = sum((v - mean) ** 2 for v in vs) / len(vs)
    std = math.sqrt(var)
    return round(mean / std, 4) if std else None
