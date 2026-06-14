from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LotConsumption:
    index: int  # position of the lot in the input list
    take: int  # units drawn from that lot
    cost: float  # take × unit_price


@dataclass
class FifoPlan:
    consumed: int
    cost: float
    lines: list[LotConsumption] = field(default_factory=list)


def plan_fifo(lots: list[tuple[int, Optional[float]]], need: int) -> FifoPlan:
    """
    Draw ``need`` units from ``lots`` ([(quantity, unit_price)], FIFO order).

    Returns which lots to draw from (by index), the units taken and the raw
    (unrounded) running cost. The caller applies the mutation and rounds.
    """
    remaining = need
    consumed = 0
    cost = 0.0
    lines: list[LotConsumption] = []
    for i, (qty, price) in enumerate(lots):
        if remaining <= 0:
            break
        take = min(qty, remaining)
        line_cost = take * (price or 0)
        cost += line_cost
        consumed += take
        remaining -= take
        lines.append(LotConsumption(i, take, line_cost))
    return FifoPlan(consumed, cost, lines)
