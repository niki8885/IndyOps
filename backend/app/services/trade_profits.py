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


def match_trades(txns: list[dict], broker_pct: float = 0.0, tax_pct: float = 0.0) -> dict:
    """FIFO-match a stream of market transactions into realized trades.

    ``txns`` are dicts with ``type_id``, ``is_buy`` (bool), ``quantity`` (int),
    ``unit_price`` (float), ``date`` (datetime) and optional ``name``. The stream may
    pool transactions from *several characters* — common when an alt buys (e.g. in Jita)
    and another character sells — so a buy on one char can back a sell on another. Each
    txn may carry its own ``broker_pct``/``tax_pct`` (the owning character's skill rates);
    the ``broker_pct``/``tax_pct`` args are the fallback when a txn omits them. A txn may
    also carry ``character_id``/``character_name`` (the seller's) and ``transaction_id`` (the
    sell's ESI id), both copied onto the realized row — ``transaction_id`` becomes
    ``sell_tx_id``, a stable per-row key the UI uses to exclude/hide individual trades.

    Returns ``{"rows": [...], "unmatched": {type_id: units}}`` — one realized trade row per
    sell (matched portion only), and the count of sell units with no tracked buy. Buy-side
    broker fee uses each consumed lot's own buyer rate; sell-side broker + sales tax use the
    selling txn's rate."""
    # chronological; on a tie a same-timestamp buy is processed before the sell so it
    # can back it (buys sort key 0, sells 1).
    ordered = sorted(txns, key=lambda t: (t.get("date"), 0 if t.get("is_buy") else 1))
    queues: dict = {}            # type_id -> list of [qty_remaining, unit_price, broker_pct] (FIFO)
    rows: list = []
    unmatched: dict = {}

    for t in ordered:
        tid = t.get("type_id")
        qty = int(t.get("quantity") or 0)
        price = float(t.get("unit_price") or 0.0)
        if qty <= 0:
            continue
        t_broker = float(t.get("broker_pct", broker_pct) or 0.0)
        if t.get("is_buy"):
            queues.setdefault(tid, []).append([qty, price, t_broker])
            continue

        # sell — consume the oldest buy lots
        t_tax = float(t.get("tax_pct", tax_pct) or 0.0)
        remaining = qty
        matched = 0
        buy_value = 0.0
        broker_buy = 0.0          # buy-side broker fee, per lot's own buyer rate
        q = queues.get(tid) or []
        while remaining > 0 and q:
            lot = q[0]
            take = min(remaining, lot[0])
            buy_value += take * lot[1]
            broker_buy += take * lot[1] * lot[2] / 100.0
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
        broker_sell = sell_value * t_broker / 100.0
        sales_tax = sell_value * t_tax / 100.0
        profit = sell_value - buy_value - broker_buy - broker_sell - sales_tax
        rows.append({
            "date": _day(t.get("date")),
            "type_id": tid,
            "name": t.get("name"),
            "sell_tx_id": t.get("transaction_id"),   # stable per-row key for exclude/hide
            "character_id": t.get("character_id"),
            "character_name": t.get("character_name"),
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

    # win/loss + risk metrics: a "win" is a realized trade row with positive profit.
    wins = [r["profit"] for r in rows if r["profit"] > 0]
    losses = [r["profit"] for r in rows if r["profit"] < 0]
    gross_loss = -sum(losses)
    n_days = len(series)

    return {
        "total_buy": round(total_buy, 2),
        "total_sell": round(total_sell, 2),
        "total_broker": round(total_broker, 2),
        "total_tax": round(total_tax, 2),
        "total_profit": round(total_profit, 2),
        "units": units,
        "trade_count": len(rows),
        "avg_margin": round(total_profit / total_buy * 100, 2) if total_buy else None,
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(rows) * 100, 1) if rows else None,
        "profit_factor": round(sum(wins) / gross_loss, 2) if gross_loss else None,
        "avg_profit": round(total_profit / len(rows), 2) if rows else None,
        "profit_per_day": round(total_profit / n_days, 2) if n_days else None,
        "series": sorted(series.values(), key=lambda x: x["date"]),
        "by_item": sorted(by_item.values(), key=lambda x: -x["profit"]),
    }
