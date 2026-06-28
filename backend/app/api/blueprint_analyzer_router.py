"""
Blueprint Collection Analyzer (IO-59 companion).

Paste a blueprint collection (one name per line, repeats grouped), pick the factories,
ME/TE, runs and where materials are bought — then rank which blueprints are worth building
by ROI and income-per-hour, with a scatter. No Monte-Carlo (the analyzer is the fast,
deterministic counterpart to the Reaction Planner): it reuses the same native engine,
pricing and slot-fill, only the candidate set comes from the pasted list instead of an SDE
sweep.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters import market
from app.adapters import reaction_planner_engine as rpe
from app.api.manufacturing_router import (
    ChainCalcRequest, ChainStructure, _build_facilities, _cj_two_sided, _industry_profile,
    _profile_out, _region_two_sided, _resolve_acquire_prices,
)
from app.api.reaction_planner_router import (
    JITA_FORGE_REGION, MAX_SWEEP_CANDIDATES, SCAM_RATIO, _candidate_out, _slot_out,
)
from app.core.database import UserDB, get_db
from app.core.database_eve import EveSessionLocal
from app.core.security import get_current_user
from app.repositories import eve as eve_repo
from app.services import slot_fill
from app.services.blueprint_collection import parse_blueprint_list
from app.services.chain import from_bom
from app.services.reaction_planner import Candidate, SellConfig

logger = logging.getLogger(__name__)
router = APIRouter()


class BlueprintEntry(BaseModel):
    name: str
    count: int = 1


class BlueprintAnalyzeRequest(BaseModel):
    blueprint_text: str = ""                 # pasted list (one per line, repeats grouped)
    blueprints: List[BlueprintEntry] = []    # or a pre-grouped list
    me_pct: float = 0.0                       # ME, applied to every target blueprint
    te_pct: float = 0.0                       # TE
    runs: int = 10                            # runs per blueprint copy
    buy_materials: bool = True                # True = buy all materials; False = optimal make-vs-buy
    # Facilities + slots (same as the Reaction Planner).
    structures: List[ChainStructure] = []
    man_slots: int = 0
    react_slots: int = 0
    horizon_hours: float = 24.0
    # Buy side — base regions + C-J, like the calculator.
    region_id: int = JITA_FORGE_REGION
    region_ids: List[int] = []
    include_cj: bool = False
    price_basis: str = "buy"
    region_sides: dict[int, str] = {}
    cj_side: Optional[str] = None
    price_rules: list = []
    # Sell side.
    sell_venue: str = "jita_sell"
    freight_per_unit: float = 0.0
    produce_character_id: Optional[int] = None
    sell_character_id: Optional[int] = None
    max_candidates: int = 100
    max_depth: int = 8


def _candidate_request(target, qty, tree, buy_prices, adj, facilities, me, te,
                       tm_man, tm_react, buy_materials):
    """Build the target blueprint's product (force-made, with the chosen ME/TE). When
    ``buy_materials`` every other node is force-bought (single-level); else the chain
    decides make-vs-buy optimally."""
    overrides = {target: (int(round(me)), int(round(te)))}
    req = from_bom(target, qty, tree, buy_prices, adj, facilities, node_overrides=overrides,
                   time_mult_man=tm_man, time_mult_react=tm_react)
    n = req.nodes.get(target)
    if n and n.recipes:
        req.nodes[target] = replace(n, buy_price=None)
    if buy_materials:
        for tid, nn in list(req.nodes.items()):
            if tid != target and nn.recipes and nn.buy_price is not None:
                req.nodes[tid] = replace(nn, recipes=())
    return req


@router.post("/analyze")
async def analyze(body: BlueprintAnalyzeRequest,
                  current_user: UserDB = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Parse + group the collection, resolve each blueprint to its product, cost and rank."""
    entries = ([{"name": e.name, "count": e.count} for e in body.blueprints]
               if body.blueprints else parse_blueprint_list(body.blueprint_text))
    if not entries:
        raise HTTPException(400, "No blueprints in the list")

    max_n = max(1, min(body.max_candidates, MAX_SWEEP_CANDIDATES))
    runs = max(1, body.runs)
    unresolved: list[str] = []

    eve_db = EveSessionLocal()
    try:
        resolved = eve_repo.types_by_name(eve_db, [e["name"] for e in entries])
        bp_ids: list[int] = []
        bp_of: dict[str, int] = {}
        for e in entries:
            r = resolved.get(e["name"].strip().lower())
            if r:
                bp_of[e["name"]] = r["type_id"]
                bp_ids.append(r["type_id"])
            else:
                unresolved.append(e["name"])
        prods = eve_repo.products_for_blueprints(eve_db, bp_ids)

        # Group by the produced type (the candidate), summing copies; keep the pasted name.
        groups: dict[int, dict] = {}
        for e in entries:
            bp = bp_of.get(e["name"])
            p = prods.get(bp) if bp else None
            if not p:
                if bp and e["name"] not in unresolved:
                    unresolved.append(e["name"])
                continue
            pt = p["product_type_id"]
            g = groups.setdefault(pt, {"count": 0, "qty_per_run": p["qty_per_run"] or 1,
                                       "name": e["name"]})
            g["count"] += max(1, e["count"])
        if not groups:
            raise HTTPException(400, "No blueprint in the list resolved to a buildable product")
        # cap distinct products
        group_items = list(groups.items())[:max_n]
        truncated = len(groups) > max_n
        groups = dict(group_items)

        trees = {pt: eve_repo.bom_tree(eve_db, pt, body.max_depth) for pt in groups}
    finally:
        eve_db.close()

    groups = {pt: g for pt, g in groups.items() if trees[pt].get(pt, {}).get("recipes")}
    if not groups:
        raise HTTPException(400, "No buildable blueprint product in the list")

    union_ids = sorted({tid for pt in groups for tid in trees[pt]})
    target_ids = list(groups)
    eff_region_ids = body.region_ids if body.region_ids else [body.region_id]

    try:
        adj = market.esi_adjusted_prices()
    except Exception:
        adj = {}
    region_data = {rid: _region_two_sided(rid, union_ids) for rid in eff_region_ids}
    cj_data = await _cj_two_sided(union_ids) if body.include_cj else {}
    group_name_of = {tid: trees[pt].get(tid, {}).get("group_name") for pt in groups for tid in trees[pt]}
    rules = [{"group": r.get("group"), "side": r.get("side")} for r in (body.price_rules or [])]
    buy_prices, _src, _flags = _resolve_acquire_prices(
        union_ids, eff_region_ids, region_data, cj_data, adj, SCAM_RATIO,
        basis=body.price_basis, region_sides=body.region_sides, cj_side=body.cj_side,
        rules=rules, group_of=group_name_of, overrides={})

    if body.sell_venue == "cj_sell":
        cj_sell = cj_data if cj_data else await _cj_two_sided(target_ids)
        sell_price = {tid: (cj_sell.get(tid) or {}).get("sell") for tid in target_ids}
    else:
        sell_two = region_data.get(JITA_FORGE_REGION) or _region_two_sided(JITA_FORGE_REGION, target_ids)
        sell_price = {tid: (sell_two.get(tid) or {}).get("sell") for tid in target_ids}

    # Facilities carry NO global ME/TE — the user's ME/TE applies only to the pasted
    # blueprints (their targets) via per-node overrides, not to bought/sub-component nodes.
    facilities = _build_facilities(
        ChainCalcRequest(product_type_id=0, structures=body.structures, me_pct=0, te_pct=0),
        db, current_user.id)
    produce_profile = _industry_profile(db, current_user.id, body.produce_character_id)
    sell_profile = _industry_profile(db, current_user.id, body.sell_character_id)
    tm_man = produce_profile.man_time_mult if produce_profile else 1.0
    tm_react = produce_profile.react_time_mult if produce_profile else 1.0
    sales_tax = sell_profile.sales_tax_pct if sell_profile else 0.0
    broker = sell_profile.broker_fee_pct if sell_profile else 0.0

    cands: list[Candidate] = []
    for pt, g in groups.items():
        qty = max(1, runs * (g["qty_per_run"] or 1))   # one blueprint copy, `runs` runs
        req = _candidate_request(pt, qty, trees[pt], buy_prices, adj, facilities,
                                 body.me_pct, body.te_pct, tm_man, tm_react, body.buy_materials)
        sell = SellConfig(unit_price=float(sell_price.get(pt) or 0.0),
                          sales_tax_pct=sales_tax, broker_fee_pct=broker,
                          freight_per_unit=body.freight_per_unit)
        cands.append(Candidate(pt, g["name"], sell, req, bought=None))

    results, engine = rpe.analyze(cands, body.man_slots, body.react_slots)

    horizon_s = int(max(1.0, body.horizon_hours) * 3600)
    slot_cands = [
        slot_fill.SlotCandidate(
            type_id=r.type_id, name=r.name, react_time_s=r.react_time_s, man_time_s=r.man_time_s,
            profit=float(r.profit), isk_per_hour=float(r.isk_per_hour),
            max_count=groups[r.type_id]["count"])     # at most as many copies as the user owns
        for r in results
    ]
    fill = slot_fill.fill_slots(slot_cands, body.man_slots, body.react_slots, horizon_s)

    out_candidates = []
    scatter = []
    for r in results:
        count = groups[r.type_id]["count"]
        d = _candidate_out(r)
        d["count"] = count
        d["blueprint_name"] = groups[r.type_id]["name"]
        d["runs"] = runs
        d["group_profit"] = float(r.profit) * count          # if all owned copies are run
        out_candidates.append(d)
        scatter.append({"type_id": r.type_id, "name": r.name, "roi": float(r.roi),
                        "isk_per_hour": float(r.isk_per_hour), "profit": float(r.profit)})

    return {
        "candidates": out_candidates,
        "slot_fill": _slot_out(fill),
        "scatter": scatter,
        "engine": engine,
        "resolved": len(groups),
        "unresolved": sorted(set(unresolved)),
        "truncated": truncated,
        "buy_materials": body.buy_materials,
        "sell_venue": body.sell_venue,
        "produce_character": _profile_out(produce_profile),
        "sell_character": _profile_out(sell_profile),
    }
