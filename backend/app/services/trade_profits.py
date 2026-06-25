"""Realized market-trade profit via FIFO buy↔sell matching (Tracking → Market).

Pure stdlib, no DB/network — the router loads one character's wallet transactions
(``EsiWalletTransaction``) and that character's market-fee rates (from skills), and
this module matches sells against the oldest buys to compute *realized* profit. See
[[indyops-service-layering]].

Cost basis is FIFO per item: each buy pushes a price lot onto the item's queue, each
sell pops the oldest lots. Only the matched portion of a sell is realized; sell units
with no tracked buy (cost basis unknown) are reported as ``unmatched`` and left out of
profit, mirroring the "missing inputs" idea from the manufacturing tracker.

Fees follow the standard order-trading model: broker fee on both the buy value and the
sell value, transaction (sales) tax on the sell value. Rates come from the character's
Accounting + Broker Relations skills (``services.skills``).
"""
from __future__ import annotations
from typing import Optional


def _day(value) -> Optional[str]:
    """ISO date (``YYYY-MM-DD``) of a datetime, or None."""
    return value.date().isoformat() if value is not None else None


def match_trades(txns: list[dict], broker_pct: float, tax_pct: float) -> dict:
    """FIFO-match one character's market transactions into realized trades.

    ``txns`` are dicts with ``type_id``, ``is_buy`` (bool), ``quantity`` (int),
    ``unit_price`` (float), ``date`` (datetime) and optional ``name``. Returns
    ``{"rows": [...], "unmatched": {type_id: units}}`` — one realized trade row per
    sell (matched portion only), and the count of sell units with no tracked buy."""
    # chronological; on a tie a same-timestamp buy is processed before the sell so it
    # can back it (buys sort key 0, sells 1).
    ordered = sorted(txns, key=lambda t: (t.get("date"), 0 if t.get("is_buy") else 1))
    queues: dict = {}            # type_id -> list of [qty_remaining, unit_price] (FIFO)
    rows: list = []
    unmatched: dict = {}

    for t in ordered:
        tid = t.get("type_id")
        qty = int(t.get("quantity") or 0)
        price = float(t.get("unit_price") or 0.0)
        if qty <= 0:
            continue
        if t.get("is_buy"):
            queues.setdefault(tid, []).append([qty, price])
            continue

        # sell — consume the oldest buy lots
        remaining = qty
        matched = 0
        buy_value = 0.0
        q = queues.get(tid) or []
        while remaining > 0 and q:
            lot = q[0]
            take = min(remaining, lot[0])
            buy_value += take * lot[1]
            matched += take
            remaining -= take
            lot[0] -= take
            if lot[0] <= 0:
                q.pop(0)
        if remaining > 0:
            unmatched[tid] = unmatched.get(tid, 0) + remaining
        if matched <= 0:
            continue

        sell_value = matched * price
        broker_buy = buy_value * broker_pct / 100.0
        broker_sell = sell_value * broker_pct / 100.0
        sales_tax = sell_value * tax_pct / 100.0
        profit = sell_value - buy_value - broker_buy - broker_sell - sales_tax
        rows.append({
            "date": _day(t.get("date")),
            "type_id": tid,
            "name": t.get("name"),
            "units": matched,
            "unit_buy": round(buy_value / matched, 2),
            "unit_sell": round(price, 2),
            "total_buy": round(buy_value, 2),
            "total_sell": round(sell_value, 2),
            "broker_buy": round(broker_buy, 2),
            "broker_sell": round(broker_sell, 2),
            "sales_tax": round(sales_tax, 2),
            "profit": round(profit, 2),
            "margin": round(profit / buy_value * 100, 2) if buy_value else None,
        })

    return {"rows": rows, "unmatched": unmatched}


def summarize_trades(rows: list[dict]) -> dict:
    """Aggregate realized trade rows into totals + metrics, a per-day profit series
    and a per-item breakdown. Pure: the router filters ``rows`` by date first."""
    total_buy = total_sell = total_broker = total_tax = total_profit = 0.0
    units = 0
    series: dict = {}
    by_item: dict = {}

    for r in rows:
        total_buy += r["total_buy"]
        total_sell += r["total_sell"]
        total_broker += r["broker_buy"] + r["broker_sell"]
        total_tax += r["sales_tax"]
        total_profit += r["profit"]
        units += r["units"]

        day = r.get("date")
        if day:
            s = series.setdefault(day, {"date": day, "profit": 0.0, "sell": 0.0})
            s["profit"] += r["profit"]
            s["sell"] += r["total_sell"]

        it = by_item.setdefault(r["type_id"], {
            "type_id": r["type_id"], "name": r.get("name"),
            "units": 0, "profit": 0.0, "total_sell": 0.0})
        it["units"] += r["units"]
        it["profit"] += r["profit"]
        it["total_sell"] += r["total_sell"]

    for s in series.values():
        s["profit"] = round(s["profit"], 2)
        s["sell"] = round(s["sell"], 2)
    for it in by_item.values():
        it["profit"] = round(it["profit"], 2)
        it["total_sell"] = round(it["total_sell"], 2)

    return {
        "total_buy": round(total_buy, 2),
        "total_sell": round(total_sell, 2),
        "total_broker": round(total_broker, 2),
        "total_tax": round(total_tax, 2),
        "total_profit": round(total_profit, 2),
        "units": units,
        "trade_count": len(rows),
        "avg_margin": round(total_profit / total_buy * 100, 2) if total_buy else None,
        "series": sorted(series.values(), key=lambda x: x["date"]),
        "by_item": sorted(by_item.values(), key=lambda x: -x["profit"]),
    }
