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
import io
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters import market
from app.adapters import portfolio as portfolio_engine
from app.core import config
from app.core.database import (
    UserDB, HaulCandidate, LinkedCharacter, EsiSkill, EsiStanding, get_db,
)
from app.core.database_eve import EveSessionLocal
from app.core.security import get_current_user
from app.repositories import eve as eve_repo
from app.repositories import share_repo
from app.repositories import trade_repo
from app.services import portfolio as portfolio_svc
from app.services import portfolio_report_pdf
from app.services import skills
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
        "group_id": r.group_id, "meta_group_id": r.meta_group_id,
        "jita_buy": r.jita_buy, "jita_sell": r.jita_sell,
        "cj_buy": r.cj_buy, "cj_sell": r.cj_sell,
        "volume_each": r.item_volume_m3, "daily_volume": r.daily_volume,
        "best_method": r.best_method, "profit_per_unit": r.profit_per_unit,
        "roi": r.margin_pct, "transport_per_unit": r.transport_per_unit,
    }


def _parse_meta(meta: Optional[str]) -> Optional[set[int]]:
    """CSV of meta_group_ids (e.g. "2,4") → set, or None for no filter."""
    if not meta:
        return None
    out = {int(x) for x in meta.split(",") if x.strip().isdigit()}
    return out or None


@router.get("/haul/scan")
async def haul_scan(
    min_margin: float = Query(0.0, description="ROI fraction floor, e.g. 0.05"),
    method: Optional[str] = Query(None, description="filter to one best_method"),
    category_id: Optional[int] = Query(None, description="6 Ship · 7 Module · 8 Charge · 18 Drone"),
    group: Optional[str] = Query(None, description="'drugs' → boosters (group filter, not category)"),
    meta: Optional[str] = Query(None, description="CSV of meta groups to keep: 1 T1 · 2 T2 · 4 Faction"),
    rank_by: str = Query("profit", pattern="^(profit|roi)$"),
    limit: int = Query(100, ge=1, le=500),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Auto-discovered, precomputed profitable Jita → C-J hauls (the haul-scan worker
    keeps it fresh). ESI-free read — ranked by per-unit profit or ROI."""
    group_ids = list(config.TRADE_HAUL_DRUG_GROUPS) if group == "drugs" else None
    rows = trade_repo.query_haul_candidates(
        db, min_margin=min_margin, method=method, category_id=category_id,
        group_ids=group_ids, meta_groups=_parse_meta(meta),
        rank_by=rank_by, limit=limit)
    iso, stale = _freshness(trade_repo.latest_updated_at(db, HaulCandidate))
    return {
        "route": "Jita → C-J6MT", "rank_by": rank_by,
        "updated_at": iso, "stale": stale,
        "methods": [{"key": k, "label": v[2]} for k, v in METHODS.items()],
        "items": [_scan_row(r) for r in rows],
        "count": len(rows),
    }


# ── portfolio optimizer (Markowitz over selected scanner items) ───────────────

class PortfolioRequest(BaseModel):
    type_ids: list[int] = []                # selected haul candidates (type_ids)
    budget: float = 0.0                     # target ISK to deploy
    character_id: Optional[int] = None      # LinkedCharacter.id (trading char → taxes/fees)
    courier_per_m3: float = 1200.0          # Jita → C-J courier rate
    risk_aversion: Optional[float] = None   # Markowitz λ (default from config)
    horizon_days: Optional[int] = None      # sell-through horizon for the liquidity cap
    max_weight: Optional[float] = None      # max budget share per item, 0..1 (diversification)
    participation: Optional[float] = None   # fraction of daily volume capturable, 0..1
    share_base: Optional[str] = None        # client origin, for the PDF QR/share link


def _market_fees(db: Session, user_id: int, character_id: Optional[int]) -> dict:
    """Resolve a trading character → {sales_tax_pct, broker_fee_pct} (percentages),
    mirroring manufacturing_router._industry_profile. None / unknown → config defaults."""
    default = {
        "character_id": None, "character_name": None,
        "sales_tax_pct": config.TRADE_SALES_TAX * 100.0,
        "broker_fee_pct": config.TRADE_BROKER_FEE * 100.0,
    }
    if character_id is None:
        return default
    char = (db.query(LinkedCharacter)
            .filter(LinkedCharacter.id == character_id, LinkedCharacter.user_id == user_id)
            .first())
    if not char:
        return default
    levels = {s.skill_id: (s.trained_level or 0)
              for s in db.query(EsiSkill).filter(EsiSkill.character_id == char.character_id).all()}
    st = db.query(EsiStanding).filter(EsiStanding.character_id == char.character_id).all()
    best_faction = max((s.standing or 0.0 for s in st if s.from_type == "faction"), default=0.0)
    best_corp = max((s.standing or 0.0 for s in st if s.from_type == "npc_corp"), default=0.0)
    return {
        "character_id": char.character_id, "character_name": char.character_name,
        "sales_tax_pct": skills.sales_tax_pct(levels),
        "broker_fee_pct": skills.broker_fee_pct(levels, best_faction, best_corp),
    }


def _compute_portfolio(db: Session, user: UserDB, body: PortfolioRequest) -> dict:
    """Price each selected candidate with the trader's fees + courier rate, run the
    Markowitz optimizer, and size integer buys to the ISK budget."""
    fees = _market_fees(db, user.id, body.character_id)
    broker, tax = fees["broker_fee_pct"] / 100.0, fees["sales_tax_pct"] / 100.0
    rate = max(body.courier_per_m3 or 0.0, 0.0)
    lam = body.risk_aversion if body.risk_aversion is not None else config.TRADE_PORTFOLIO_RISK_AVERSION
    horizon = body.horizon_days or config.TRADE_PORTFOLIO_HORIZON_DAYS
    participation = (body.participation if body.participation is not None
                     else config.TRADE_PORTFOLIO_PARTICIPATION)
    max_weight = body.max_weight if body.max_weight is not None else config.TRADE_PORTFOLIO_MAX_WEIGHT

    type_ids = [int(t) for t in (body.type_ids or [])]
    rows = (trade_repo.query_haul_candidates(db, type_ids=type_ids, limit=max(len(type_ids), 1))
            if type_ids else [])
    stats = trade_repo.load_type_stats(db, JITA_REGION, [r.item_id for r in rows])

    assets: list[dict] = []
    for r in rows:
        vol_m3 = r.item_volume_m3 or 0.0
        best = trade.best_haul_method(
            jita_buy=r.jita_buy, jita_sell=r.jita_sell, cj_buy=r.cj_buy, cj_sell=r.cj_sell,
            qty=1, broker_fee=broker, sales_tax=tax, shipping_per_unit=vol_m3 * rate)
        if not best or best["capital"] <= 0:
            continue
        cv = (stats.get(r.item_id) or {}).get("volatility_cv")
        base_sigma = cv if (cv and cv > 0) else config.TRADE_PORTFOLIO_DEFAULT_SIGMA
        sigma = max(base_sigma, config.TRADE_PORTFOLIO_MIN_SIGMA)  # don't treat arbitrage as riskless
        assets.append({
            "type_id": r.item_id, "name": r.type_name, "category_id": r.category_id,
            "unit_cost": best["capital"], "unit_profit": best["profit"], "roi": best["roi"],
            "sigma": sigma, "unit_vol_m3": vol_m3, "daily_volume": r.daily_volume,
            "best_method": best["method"],
        })

    priced_ids = {a["type_id"] for a in assets}
    unmatched = [t for t in type_ids if t not in priced_ids]

    if assets:
        mu_v = [a["roi"] for a in assets]
        sig_v = [a["sigma"] for a in assets]
        weights, _metrics, engine = portfolio_engine.optimize_weights(mu_v, sig_v, lam)
        result = portfolio_svc.build_portfolio(
            assets, weights, body.budget, horizon_days=horizon,
            participation=participation, max_weight=max_weight)
        t = result["totals"]
        # the chosen point is the REALIZED portfolio (caps push it inside the frontier)
        result["frontier"] = {
            "points": portfolio_svc.efficient_frontier(mu_v, sig_v),
            "chosen": {"risk_aversion": lam, "stddev": t["stddev"], "exp_return": t["exp_return"]},
            "assets": [{"name": a["name"], "stddev": a["sigma"], "exp_return": a["roi"]} for a in assets],
        }
    else:
        engine = "python"
        result = {"allocations": [], "totals": {
            "budget": round(max(body.budget or 0.0, 0.0), 2), "capital_used": 0.0, "leftover": 0.0,
            "expected_profit": 0.0, "portfolio_roi": 0.0, "total_volume_m3": 0.0,
            "stddev": 0.0, "exp_return": 0.0, "n_assets": 0, "n_considered": 0}}

    meta = {
        "character_id": fees["character_id"], "character_name": fees["character_name"],
        "sales_tax_pct": round(fees["sales_tax_pct"], 4), "broker_fee_pct": round(fees["broker_fee_pct"], 4),
        "courier_per_m3": rate, "budget": round(max(body.budget or 0.0, 0.0), 2),
        "risk_aversion": lam, "horizon_days": horizon, "participation": participation,
        "max_weight": max_weight, "engine": engine,
    }
    return {"meta": meta, "result": result, "unmatched": unmatched}


@router.post("/haul/portfolio")
def haul_portfolio(body: PortfolioRequest, current_user: UserDB = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Markowitz mean-variance allocation of an ISK budget across selected Jita → C-J
    haul candidates, priced with the trading character's taxes + courier rate."""
    return {"route": "Jita → C-J6MT", **_compute_portfolio(db, current_user, body)}


@router.post("/haul/portfolio/pdf")
def haul_portfolio_pdf(body: PortfolioRequest, current_user: UserDB = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """The same optimized portfolio as a branded PDF report (production-style letterhead
    + share code/QR)."""
    data = _compute_portfolio(db, current_user, body)
    code = share_repo.store_share(db, "haulport", body.model_dump(exclude={"share_base"}))
    base = (body.share_base or "").rstrip("/")
    share_url = f"{base}/market?portfolio={code}" if base else code
    report = {
        "meta": {**data["meta"], "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")},
        "result": data["result"], "share_code": code, "share_url": share_url,
    }
    pdf = portfolio_report_pdf.render_portfolio_pdf(report)
    headers = {"Content-Disposition": f'attachment; filename="haul-portfolio-{code}.pdf"'}
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf", headers=headers)
