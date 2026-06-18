"""
Pure trade-preprocessing math for the cross-hub optimizer + station trading.

No I/O, no ORM — every function takes plain numbers/lists and returns plain
numbers/dicts, so it is fully unit-testable (mirrors ``services/indices.py``).

Layer-2 "remove garbage" filters live here: liquidity (daily volume), volatility
(coefficient of variation), and spread (margin must stay positive after broker
fee + sales tax + transport). Margins are expressed as a fraction (0.1 = 10%).
"""
from __future__ import annotations
import math


def daily_volume(history: list[dict] | None) -> float:
    """Mean daily traded units over the given ESI history slice (0 if empty)."""
    if not history:
        return 0.0
    vols = [float(d.get("volume") or 0) for d in history]
    return sum(vols) / len(vols) if vols else 0.0


def volatility_cv(history: list[dict] | None) -> float | None:
    """Coefficient of variation std/mean of daily average price over the slice.

    None if fewer than 2 points or the mean is non-positive (can't normalise).
    Uses the population std to match ``services.indices.liquidity``.
    """
    if not history:
        return None
    prices = [float(d.get("average") or 0) for d in history]
    prices = [p for p in prices if p > 0]
    if len(prices) < 2:
        return None
    mean = sum(prices) / len(prices)
    if mean <= 0:
        return None
    var = sum((p - mean) ** 2 for p in prices) / len(prices)
    return round(math.sqrt(var) / mean, 6)


def transport_cost_per_unit(item_volume_m3: float, jumps: int, isk_per_jump_m3: float) -> float:
    """Per-unit haul cost = volume(m³) · jumps · rate (mirrors delivery.regular_cost)."""
    return max(item_volume_m3 or 0.0, 0.0) * max(jumps, 0) * max(isk_per_jump_m3 or 0.0, 0.0)


def _result(profit: float, cost: float) -> dict:
    """Profit + ROI-style margin fraction (profit / capital outlay)."""
    margin = profit / cost if cost > 0 else 0.0
    return {"profit_isk": round(profit, 2), "margin_pct": round(margin, 6)}


def patient_margin(buy_price: float, dest_sell_price: float, broker_fee: float,
                   sales_tax: float, transport_cost: float = 0.0) -> dict:
    """Sell by *placing a sell order* at the destination.

    You buy from existing sell orders at the source (no broker fee), haul, then
    list a sell order — paying broker fee on listing + sales tax on the sale.
    """
    revenue = dest_sell_price * (1.0 - broker_fee - sales_tax)
    cost = buy_price + transport_cost
    return _result(revenue - cost, cost)


def instant_margin(buy_price: float, dest_buy_price: float, sales_tax: float,
                   transport_cost: float = 0.0) -> dict:
    """Sell *into buy orders* at the destination — sales tax only, no broker fee."""
    revenue = dest_buy_price * (1.0 - sales_tax)
    cost = buy_price + transport_cost
    return _result(revenue - cost, cost)


def station_margin(station_buy: float, station_sell: float, broker_fee: float,
                   sales_tax: float) -> dict:
    """In-station flip: buy with a buy order, sell with a sell order.

    Broker fee is charged twice (placing the buy order and the sell order) plus
    sales tax on the sale; no transport.
    """
    cost = station_buy * (1.0 + broker_fee)
    revenue = station_sell * (1.0 - broker_fee - sales_tax)
    return _result(revenue - cost, cost)


def passes_filters(daily_vol: float, cv: float | None, margin_pct: float, *,
                   min_volume: float, max_cv: float) -> bool:
    """The 3 Layer-2 filters: liquidity, volatility, spread (positive net margin)."""
    if daily_vol < min_volume:                 # liquidity
        return False
    if cv is None or cv > max_cv:              # volatility
        return False
    if margin_pct <= 0:                        # spread (margin already net of fees+transport)
        return False
    return True


def volume_scores(daily_volumes: dict[int, float]) -> dict[int, float]:
    """Normalise each type's daily volume to 0..1 via log1p min-max over the set.

    EVE volumes are heavily right-skewed, so we scale on log1p. A degenerate set
    (one item, or all equal) maps to 1.0 when there is volume, else 0.0.
    """
    if not daily_volumes:
        return {}
    logs = {tid: math.log1p(max(v, 0.0)) for tid, v in daily_volumes.items()}
    lo, hi = min(logs.values()), max(logs.values())
    if hi <= lo:
        score = 1.0 if hi > 0 else 0.0
        return {tid: score for tid in logs}
    span = hi - lo
    return {tid: round((l - lo) / span, 6) for tid, l in logs.items()}
