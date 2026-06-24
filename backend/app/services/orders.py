"""Pure helpers for the account Orders view.

Covers the three derived bits the table needs that aren't stored on the order:
expiry (issued + duration), highlight flags (expiring soon / volume running low),
and the competitive **price status** vs the live region order book. Plus a summary
aggregation for the section headers and the per-station / per-system distribution.

Pure module — no ORM / web / I/O. Callers pass plain dicts / values.
"""
import datetime
from typing import Iterable, Optional

EXPIRING_SOON_DAYS = 3       # highlight orders expiring within this many days
LOW_VOLUME_FRACTION = 0.10   # highlight orders with ≤10% of their original volume left


def expires_at(issued: Optional[datetime.datetime], duration: Optional[int]) -> Optional[datetime.datetime]:
    """When an order lapses: ``issued + duration`` days. None if either is missing."""
    if not issued or duration is None:
        return None
    return issued + datetime.timedelta(days=int(duration))


def _seconds_until(when: Optional[datetime.datetime], now: datetime.datetime) -> Optional[float]:
    if not when:
        return None
    return (when - now).total_seconds()


def classify(order: dict, now: datetime.datetime,
             expiring_days: int = EXPIRING_SOON_DAYS,
             low_fraction: float = LOW_VOLUME_FRACTION) -> dict:
    """Highlight flags + computed expiry for a single order dict.

    Needs ``issued``, ``duration``, ``volume_remain``, ``volume_total``. Returns
    ``{expires_at, expiring_soon, low_volume}``."""
    exp = expires_at(order.get("issued"), order.get("duration"))
    secs = _seconds_until(exp, now)
    expiring = secs is not None and 0 <= secs <= expiring_days * 86400
    total = order.get("volume_total") or 0
    remain = order.get("volume_remain") or 0
    low = bool(total) and (remain / total) <= low_fraction
    return {
        "expires_at": exp,
        "expiring_soon": bool(expiring),
        "low_volume": bool(low),
    }


def price_compare(my_price: Optional[float], is_buy: bool,
                  competing_prices: Iterable[Optional[float]]) -> dict:
    """Status of my order's price vs the best competing order in the same book.

    Sell orders: cheaper wins, so the best competitor is the **lowest** price and I'm
    ``best`` when I'm at or below it. Buy orders: higher wins, best competitor is the
    **highest** price and I'm ``best`` when I'm at or above it. ``difference`` is the
    signed gap ``my_price − best_competitor`` (for a sell, positive = I'm dearer =
    losing; for a buy, positive = I bid more = winning).

    Returns ``{status, difference, difference_pct, best_competitor}`` where status is
    ``best`` / ``outbid`` / ``only`` (no competition) / ``None`` (no price)."""
    if my_price is None:
        return {"status": None, "difference": None, "difference_pct": None, "best_competitor": None}
    prices = [p for p in competing_prices if p is not None]
    if not prices:
        return {"status": "only", "difference": None, "difference_pct": None, "best_competitor": None}

    best = min(prices) if not is_buy else max(prices)
    diff = my_price - best
    is_best = (my_price <= best) if not is_buy else (my_price >= best)
    pct = (diff / best * 100.0) if best else None
    return {
        "status": "best" if is_best else "outbid",
        "difference": diff,
        "difference_pct": pct,
        "best_competitor": best,
    }


def _value(row: dict) -> float:
    return (row.get("price") or 0) * (row.get("volume_remain") or 0)


def _group(rows: list, field: str) -> list:
    """Aggregate rows by a name field → ``[{name, count, value}]``, richest first."""
    agg: dict = {}
    for r in rows:
        name = r.get(field) or "Unknown"
        g = agg.setdefault(name, {"name": name, "count": 0, "value": 0.0})
        g["count"] += 1
        g["value"] += _value(r)
    return sorted(agg.values(), key=lambda g: g["value"], reverse=True)


def summarize(sell_rows: list, buy_rows: list) -> dict:
    """Section-header totals + station/system distribution from enriched rows.

    Rows are expected to carry ``price``, ``volume_remain``, ``escrow`` and the
    name fields ``station`` / ``system`` (see the router enrichment)."""
    sell_isk = sum(_value(r) for r in sell_rows)
    buy_isk = sum(_value(r) for r in buy_rows)
    escrow = sum(r.get("escrow") or 0 for r in buy_rows)
    all_rows = sell_rows + buy_rows
    return {
        "sell_count": len(sell_rows),
        "buy_count": len(buy_rows),
        "sell_isk": sell_isk,
        "buy_isk": buy_isk,
        "buy_escrow": escrow,
        "remaining_to_cover": buy_isk - escrow,
        "by_station": _group(all_rows, "station"),
        "by_system": _group(all_rows, "system"),
    }
