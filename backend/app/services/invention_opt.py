"""
Invention optimizer ORACLE (Python). Enumerates every (final product × decryptor)
combination, evaluates its production economics via ``invention.evaluate``, and
ranks them by a z-scored composite of production metrics.

This is the spec the Haskell engine (haskell/invention-optimizer) must match
exactly on rank order; app.adapters.invention_optimizer prefers the native binary
and falls back here. Mirrors the risk-engine pattern. See
[[indyops-fortran-analytics-engine]] for the parity-engine convention.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from app.services import invention as inv
from app.services.invention import Decryptor, Material

# (metric key, sign [+1 higher better / −1 lower], default weight). Mirror in Haskell.
_METRICS: list[tuple[str, float, float]] = [
    ("profit_per_run", 1.0, 1.0),
    ("margin_pct", 1.0, 1.0),
    ("profit_per_unit", 1.0, 0.5),
    ("cost_per_bpc", -1.0, 0.5),
    ("probability", 1.0, 0.5),
]
_MISSING_HIGH = 1e18    # stand-in for "no value" on a lower-is-better metric
_MISSING_LOW = -1e18    # stand-in for "no value" on a higher-is-better metric


@dataclass
class OptInput:
    """One invention final product, with its per-product economics resolved by the
    router (prices, skills for THIS product's invention, T2 BOM)."""
    product_type_id: int
    product_name: str
    base_prob: float
    base_runs: int
    units_per_run: int
    datacore_cost: float
    invention_install_cost: float
    manuf_install_per_run: float
    sell_per_unit: float
    materials: list[Material]
    mat_extra_mult: float
    encryption: int
    sci1: int
    sci2: int


def _metric(cand: dict, key: str, sign: float) -> float:
    v = cand.get(key)
    if v is None:
        return _MISSING_HIGH if sign < 0 else _MISSING_LOW
    return float(v)


def _rank(cands: list[dict], weights: Optional[dict[str, float]]) -> list[dict]:
    if not cands:
        return []
    n = len(cands)
    scores = [0.0] * n
    for key, sign, dflt in _METRICS:
        w = dflt if not weights or key not in weights else weights[key]
        vals = [_metric(c, key, sign) for c in cands]
        m = sum(vals) / n
        sd = (sum((v - m) ** 2 for v in vals) / n) ** 0.5
        if sd > 0:
            for i, v in enumerate(vals):
                scores[i] += w * sign * (v - m) / sd
    ordered = sorted(
        zip(cands, scores),
        key=lambda cs: (-cs[1], -_metric(cs[0], "profit_per_run", 1.0), cs[0]["label"]),
    )
    out = []
    for rank, (c, sc) in enumerate(ordered, start=1):
        out.append({**c, "rank": rank, "score": sc})
    return out


def optimize(products: list[OptInput], decryptors: list[Decryptor],
             decryptor_prices: dict[int, float],
             weights: Optional[dict[str, float]] = None) -> list[dict]:
    """Enumerate products × decryptors, evaluate each, return the ranked list."""
    cands: list[dict] = []
    for p in products:
        for d in decryptors:
            dprice = decryptor_prices.get(d.type_id, 0.0) if d.type_id else 0.0
            row = inv.evaluate(
                base_prob=p.base_prob, base_runs=p.base_runs, units_per_run=p.units_per_run,
                datacore_cost=p.datacore_cost, decryptor_price=dprice,
                invention_install_cost=p.invention_install_cost,
                manuf_install_per_run=p.manuf_install_per_run, sell_per_unit=p.sell_per_unit,
                materials=p.materials, mat_extra_mult=p.mat_extra_mult,
                encryption=p.encryption, sci1=p.sci1, sci2=p.sci2, decryptor=d,
            )
            row["label"] = f"{p.product_name} / {d.name}"
            row["product_type_id"] = p.product_type_id
            row["product_name"] = p.product_name
            cands.append(row)
    return _rank(cands, weights)
