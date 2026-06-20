"""
Jita → C-J haul evaluator: paste a shopping list, pick acquisition/sale methods +
a courier rate, and get per-item profit / ROI so you can decide whether to buy in
Jita and haul it to C-J6MT to sell.

Live prices: Jita from Fuzzwork aggregates (The Forge), C-J from the appraise.gnf.lt
scrape (``market.gnf_local``, parallel) — the same two sources the Ore Acquisition
page compares. Pure economics live in ``services.trade.haul_eval``.
"""
from __future__ import annotations
import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters import market
from app.core import config
from app.core.database import UserDB, HaulCandidate, get_db
from app.core.database_eve import EveSessionLocal
from app.core.security import get_current_user
from app.repositories import eve as eve_repo
from app.repositories import trade_repo
from app.services import trade

router = APIRouter()

JITA_REGION = 10000002          # The Forge
MAX_ITEMS = 80                  # cap the C-J scrape fan-out

# method definitions are shared with the auto scanner (services.trade.HAUL_METHODS):
# key "<jita-side>_<cj-side>", each side naming the order book you transact against.
METHODS = trade.HAUL_METHODS
_DEFAULT_METHOD = "sell_buy"


class HaulRequest(BaseModel):
    paste: str = ""                         # EVE clipboard / multibuy: "Name<tab>qty…"
    methods: list[str] = [_DEFAULT_METHOD]
    shipping_per_m3: float = 0.0            # courier rate ISK/m³ (Jita → C-J)
    shipping_flat: float = 0.0             # one-off total, allocated across items by volume
    broker_fee_pct: float = 3.0
    sales_tax_pct: float = 4.5
    rank_by: str = "profit"                 # profit | roi


# ── paste parsing ─────────────────────────────────────────────────────────────

_QTY_LINE = re.compile(r"^(.*?)(?:\s+|\s*x\s*)([\d.,\s]+)$", re.IGNORECASE)


def _try_num(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", "").replace(" ", ""))
    except (ValueError, AttributeError):
        return None


def _parse_lines(text: str) -> list[tuple[str, float]]:
    """Pasted lines → (name, qty). Handles ``Name<tab>qty<tab>price<tab>total`` (the
    market/inventory copy), ``Qty<tab>Name``, ``Name x10``, ``Name 1,000`` and a bare
    ``Name`` (qty 1)."""
    out: list[tuple[str, float]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if "\t" in line:
            parts = [p.strip() for p in line.split("\t")]
            a, b = parts[0], (parts[1] if len(parts) > 1 else "")
            qa, qb = _try_num(a), _try_num(b)
            if qa is not None and qb is None:        # "Qty<tab>Name"
                out.append((b, qa))
            elif qb is not None:                     # "Name<tab>Qty[<tab>price…]"
                out.append((a, qb))
            else:
                out.append((a, 1.0))
            continue
        m = _QTY_LINE.match(line)
        if m and _try_num(m.group(2)) is not None:
            out.append((m.group(1).strip(), _try_num(m.group(2))))
        else:
            out.append((line, 1.0))
    return out


# ── price fetch (mirrors ore_router) ──────────────────────────────────────────

def _jita_two_sided(type_ids: list[int]) -> dict[int, dict]:
    """Per-type ``{'buy','sell'}`` from one Fuzzwork aggregate fetch (The Forge)."""
    agg = market.fuzzwork_aggregates_or_empty(JITA_REGION, type_ids)
    out: dict[int, dict] = {}
    for tid in type_ids:
        s = agg.get(str(tid)) or {}
        b, se = s.get("buy") or {}, s.get("sell") or {}
        # percentile is the robust volume-weighted price (ignores scam outliers); fall
        # back to the best order (buy max / sell min) — matches the Ore Acquisition page.
        out[tid] = {"buy": _try_num(str(b.get("percentile") or b.get("max") or "")),
                    "sell": _try_num(str(se.get("percentile") or se.get("min") or ""))}
    return out


async def _cj_two_sided(type_ids: list[int]) -> dict[int, dict]:
    """Per-type ``{'buy','sell'}`` from the C-J6MT scrape (parallel, best-effort)."""
    if not type_ids:
        return {}
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = await asyncio.gather(
            *[loop.run_in_executor(ex, market.gnf_local, tid) for tid in type_ids]
        )
    return {tid: {"buy": p.get("buy"), "sell": p.get("sell")}
            for tid, p in zip(type_ids, results) if p}


# ── endpoint ──────────────────────────────────────────────────────────────────

@router.post("/haul")
async def evaluate_haul(body: HaulRequest, current_user: UserDB = Depends(get_current_user)):
    """Evaluate a Jita → C-J shopping list. Returns per-item profit/ROI for each chosen
    method, the best method per item, and a portfolio total to answer 'buy & haul now?'."""
    methods = [m for m in body.methods if m in METHODS] or [_DEFAULT_METHOD]
    rank_key = "roi" if body.rank_by == "roi" else "profit"
    broker, tax = body.broker_fee_pct / 100.0, body.sales_tax_pct / 100.0

    parsed = _parse_lines(body.paste)
    eve_db = EveSessionLocal()
    try:
        resolved = eve_repo.types_by_name(eve_db, [n for n, _ in parsed])
        agg: dict[int, dict] = {}
        unmatched: list[str] = []
        for name, qty in parsed:
            r = resolved.get(name.lower())
            if not r:
                unmatched.append(name)
                continue
            a = agg.setdefault(r["type_id"], {"name": r["name"], "qty": 0.0})
            a["qty"] += qty
        type_ids = list(agg.keys())[:MAX_ITEMS]
        truncated = len(agg) > MAX_ITEMS
        vols = eve_repo.volumes(eve_db, type_ids)
    finally:
        eve_db.close()

    jita = _jita_two_sided(type_ids)
    cj = await _cj_two_sided(type_ids)

    # flat shipping is spread across the list by m³ share
    total_vol = sum((vols.get(t) or 0.0) * agg[t]["qty"] for t in type_ids)
    flat = max(body.shipping_flat, 0.0)

    items: list[dict] = []
    for t in type_ids:
        qty = agg[t]["qty"]
        vol_each = vols.get(t) or 0.0
        item_vol = vol_each * qty
        flat_share = (flat * item_vol / total_vol) if (flat and total_vol > 0) else 0.0
        ship_unit = vol_each * max(body.shipping_per_m3, 0.0) + (flat_share / qty if qty > 0 else 0.0)

        j, c = jita.get(t, {}), cj.get(t, {})
        results: dict[str, dict] = {}
        for mk in methods:
            acq_side, sell_side, _ = METHODS[mk]
            r = trade.haul_eval(
                jita_buy=j.get("buy"), jita_sell=j.get("sell"),
                cj_buy=c.get("buy"), cj_sell=c.get("sell"), qty=qty,
                acquire_side=acq_side, sell_side=sell_side,
                broker_fee=broker, sales_tax=tax, shipping_per_unit=ship_unit)
            if r:
                results[mk] = r
        best = None
        if results:
            bk = max(results, key=lambda m: results[m][rank_key])
            best = {"method": bk, **results[bk]}
        items.append({
            "type_id": t, "name": agg[t]["name"], "qty": qty,
            "volume_each": vol_each, "total_volume": round(item_vol, 2),
            "jita_buy": j.get("buy"), "jita_sell": j.get("sell"),
            "cj_buy": c.get("buy"), "cj_sell": c.get("sell"),
            "methods": results, "best": best,
            "recommend": bool(best and best["profit"] > 0),
        })

    items.sort(key=lambda x: (x["best"][rank_key] if x["best"] else float("-inf")), reverse=True)

    priced = [i for i in items if i["best"]]
    tot_capital = sum(i["best"]["capital"] for i in priced)
    tot_profit = sum(i["best"]["profit"] for i in priced)
    totals = {
        "count": len(items), "priced": len(priced),
        "recommend_count": sum(1 for i in items if i["recommend"]),
        "capital": round(tot_capital, 2), "profit": round(tot_profit, 2),
        "roi": round(tot_profit / tot_capital, 6) if tot_capital > 0 else 0.0,
        "volume": round(total_vol, 2),
    }
    return {
        "route": "Jita → C-J6MT",
        "methods": [{"key": k, "label": METHODS[k][2]} for k in methods],
        "rank_by": rank_key,
        "items": items,
        "unmatched": sorted(set(unmatched)),
        "truncated": truncated, "max_items": MAX_ITEMS,
        "prices_available": bool(jita or cj),
        "totals": totals,
    }


# ── auto scanner (precomputed by the haul-scan worker) ────────────────────────

def _freshness(updated_at) -> tuple[Optional[str], bool]:
    if updated_at is None:
        return None, True
    ua = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=timezone.utc)
    stale = (datetime.now(timezone.utc) - ua).total_seconds() > config.TRADE_HAUL_TTL_SECONDS
    return updated_at.isoformat(), stale


def _scan_row(r: HaulCandidate) -> dict:
    return {
        "type_id": r.item_id, "name": r.type_name, "category_id": r.category_id,
        "jita_buy": r.jita_buy, "jita_sell": r.jita_sell,
        "cj_buy": r.cj_buy, "cj_sell": r.cj_sell,
        "volume_each": r.item_volume_m3, "daily_volume": r.daily_volume,
        "best_method": r.best_method, "profit_per_unit": r.profit_per_unit,
        "roi": r.margin_pct, "transport_per_unit": r.transport_per_unit,
    }


@router.get("/haul/scan")
async def haul_scan(
    min_margin: float = Query(0.0, description="ROI fraction floor, e.g. 0.05"),
    method: Optional[str] = Query(None, description="filter to one best_method"),
    category_id: Optional[int] = Query(None, description="6 Ship · 7 Module · 8 Charge · 18 Drone · 87 Fighter"),
    rank_by: str = Query("profit", pattern="^(profit|roi)$"),
    limit: int = Query(100, ge=1, le=500),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Auto-discovered, precomputed profitable Jita → C-J hauls (the haul-scan worker
    keeps it fresh). ESI-free read — ranked by per-unit profit or ROI."""
    rows = trade_repo.query_haul_candidates(
        db, min_margin=min_margin, method=method, category_id=category_id,
        rank_by=rank_by, limit=limit)
    iso, stale = _freshness(trade_repo.latest_updated_at(db, HaulCandidate))
    return {
        "route": "Jita → C-J6MT", "rank_by": rank_by,
        "updated_at": iso, "stale": stale,
        "methods": [{"key": k, "label": v[2]} for k, v in METHODS.items()],
        "items": [_scan_row(r) for r in rows],
        "count": len(rows),
    }
