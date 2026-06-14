"""
Pure warehouse sell-allocation: split a quantity across venues by strategy.

Extracted from tracking_router (``_allocate``). The router fetches live prices
and 30d history (I/O), builds Venue projections and renders the result; this
module only decides the split.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Venue:
    place_id: int
    place_name: str
    net_instant: Optional[float]   # ISK/unit selling into buy orders now (after delivery)
    net_patient: Optional[float]   # ISK/unit via a sell order (after fees + delivery)
    hist_vol: Optional[float]      # 30d avg daily volume — capacity + ETA


@dataclass
class Allocation:
    place_id: int
    place_name: str
    qty: int
    method: str
    unit_net: Optional[float]
    net_total: float
    est_days: float


def _row(v: Venue, q: int, method: str, unit: Optional[float]) -> Allocation:
    vol = v.hist_vol or 0
    days = round(q / vol, 1) if (method == "sell order" and vol) else 0
    return Allocation(v.place_id, v.place_name, q, method, unit,
                      round((unit or 0) * q, 2), days)


def allocate(venues: list[Venue], qty: int, strategy: str, balance_days: int) -> list[Allocation]:
    """
    fast       → dump everything into the best instant (buy-order) venue.
    maxprofit  → list everything as a sell order in the best venue.
    balanced   → fill best sell-order venues up to capacity (vol × days),
                 then dump the remainder instant.
    """
    instant = [v for v in venues if v.net_instant is not None]
    patient = [v for v in venues if v.net_patient is not None]

    if strategy == "fast":
        if not instant:
            return []
        v = max(instant, key=lambda v: v.net_instant)
        return [_row(v, qty, "instant (buy order)", v.net_instant)]

    if strategy == "maxprofit":
        if not patient:
            return []
        v = max(patient, key=lambda v: v.net_patient)
        return [_row(v, qty, "sell order", v.net_patient)]

    # balanced
    allocs: list[Allocation] = []
    remaining = qty
    for v in sorted(patient, key=lambda v: v.net_patient, reverse=True):
        if remaining <= 0:
            break
        cap = int((v.hist_vol or 0) * balance_days) or remaining
        take = min(remaining, cap)
        if take > 0:
            allocs.append(_row(v, take, "sell order", v.net_patient))
            remaining -= take
    if remaining > 0 and instant:
        v = max(instant, key=lambda v: v.net_instant)
        allocs.append(_row(v, remaining, "instant (buy order)", v.net_instant))
        remaining = 0
    return allocs
