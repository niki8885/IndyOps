"""Pure loot/inventory paste parsing + ISK appraisal.

``parse_lines`` is the single source for the EVE multi-line paste format (also used by
the inventory bulk import). ``appraise`` totals a basket given resolved unit prices.
Both are pure (stdlib only) so the Tracking loot tracker and the inventory importer
share them and they're easy to unit-test. See [[indyops-service-layering]].
"""
from __future__ import annotations
from typing import Optional


def _try_int(s: str) -> Optional[int]:
    try:
        return int(float(s.replace(",", "").replace(" ", "")))
    except ValueError:
        return None


def parse_lines(text: str) -> list[tuple[str, int, list[str]]]:
    """Parse tab-separated lines into ``(name, qty, warnings)`` tuples.

    Auto-detects two formats:
      ``Name<tab>Qty``  — e.g. "Megacyte\\t8"
      ``Qty<tab>Name``  — e.g. "8\\tMegacyte"
    Lines that can't be parsed produce a ``("", 0, [warning])`` tuple so the caller can
    surface them."""
    rows: list[tuple[str, int, list[str]]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            rows.append(("", 0, [f"Line {lineno}: expected Name<tab>Qty or Qty<tab>Name, got: {repr(line)}"]))
            continue

        col0, col1 = parts[0].strip(), parts[1].strip()
        qty0, qty1 = _try_int(col0), _try_int(col1)

        if qty0 is not None and qty1 is None:
            qty, name = qty0, col1          # Qty\tName
        elif qty0 is None and qty1 is not None:
            name, qty = col0, qty1          # Name\tQty
        elif qty0 is not None and qty1 is not None:
            qty, name = qty0, col1          # both numeric — EVE multi-buy style (Qty\tName)
        else:
            rows.append(("", 0, [f"Line {lineno}: could not find quantity in: {repr(line)}"]))
            continue

        if qty <= 0:
            rows.append(("", 0, [f"Line {lineno}: quantity must be positive"]))
            continue
        rows.append((name, qty, []))
    return rows


def appraise(items: list[dict], prices: dict[int, dict], basis: str = "jita_sell") -> dict:
    """Value a basket of items at the given unit prices.

    ``items`` are ``{name, type_id, qty}`` dicts. ``prices`` maps ``type_id`` →
    ``{"sell": float|None, "buy": float|None}``. ``basis`` picks the side:
    ``jita_sell`` (sell-order min — patient list value) or ``jita_buy`` (buy-order max —
    instant sell value). Returns priced line items, the grand total, and the names that
    could not be priced/resolved."""
    side = "buy" if basis == "jita_buy" else "sell"
    out_items = []
    total = 0.0
    unpriced: list[str] = []

    for it in items:
        tid = it.get("type_id")
        qty = it.get("qty") or 0
        unit = None
        if tid is not None:
            unit = (prices.get(tid) or {}).get(side)
        line_total = (unit or 0.0) * qty
        priced = unit is not None and unit > 0
        if not priced:
            unpriced.append(it.get("name"))
        else:
            total += line_total
        out_items.append({
            "name": it.get("name"),
            "type_id": tid,
            "qty": qty,
            "unit": round(unit, 2) if unit else None,
            "total": round(line_total, 2) if priced else None,
            "priced": priced,
        })

    return {
        "items": out_items,
        "total_value": round(total, 2),
        "unpriced": [n for n in unpriced if n],
        "basis": basis,
    }
