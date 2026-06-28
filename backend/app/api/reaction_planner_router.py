"""
Reaction Planner API (IO-59).

Sweeps a set of candidate products (final reaction products + T2 components), costs each
from scratch via the chain core (native Haskell ``reaction-planner`` engine, Python oracle
fallback), ranks them by ROI / income-per-hour, compares "build reactions from scratch" vs
"buy the finished reaction intermediates" for components, and fills the available
manufacturing + reaction slots so they don't idle. Monte-Carlo is on demand per candidate.

Thin router: it does the I/O (SDE reads, market prices, character profiles) and hands pure
data to the engine + ``services.slot_fill``. Buy pricing, facility building and the
force-make/force-buy node overrides are reused from ``manufacturing_router`` so the planner
shares the calculator's multi-region + C-J resolution exactly.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, replace
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters import market, sim_data
from app.adapters import profit_sim as profit_sim_engine
from app.adapters import reaction_planner_engine as rpe
from app.services import profit_sim as profit_sim_svc
from app.api import simulation_router as sim_router
from app.api.manufacturing_router import (
    ChainCalcRequest, ChainStructure, PriceRule,
    _build_facilities, _cj_two_sided, _industry_profile, _profile_out,
    _region_two_sided, _resolve_acquire_prices, _to_jsonable,
)
from app.api.simulation_router import SimParamsIn
from app.core.database import LinkedCharacter, UserDB, get_db
from app.core.database_eve import EveSessionLocal
from app.core.security import get_current_user
from app.repositories import eve as eve_repo
from app.services import reaction_planner as planner
from app.services import slot_fill
from app.services.chain import MANUFACTURING, REACTION, from_bom, solve_chain
from app.services.reaction_planner import Candidate, SellConfig
from app.services.scheduling import stage_schedule

logger = logging.getLogger(__name__)
router = APIRouter()

JITA_FORGE_REGION = 10000002      # The Forge — default sell venue ("Jita sell")
MAX_SWEEP_CANDIDATES = 200        # hard cap (each candidate is a full chain solve)
SCAM_RATIO = 0.3                  # buy-price scam guard, same default as the calculator


class ReactionSweepRequest(BaseModel):
    # Facilities: the reaction station (+ optional component factory). Their type sets
    # can_man / can_react automatically (refinery reacts, EC manufactures).
    structures: List[ChainStructure] = []
    me_pct: float = 0.0
    te_pct: float = 0.0
    # Available job slots (manual, per the spec) + planning horizon for the slot fill.
    man_slots: int = 0
    react_slots: int = 0
    horizon_hours: float = 24.0
    # Buy side — same multi-region + C-J resolution as the calculator.
    region_id: int = JITA_FORGE_REGION
    region_ids: List[int] = []
    include_cj: bool = False
    price_basis: str = "buy"
    region_sides: dict[int, str] = {}
    cj_side: Optional[str] = None
    price_rules: List[PriceRule] = []
    # Sell side — where the finished product sells, for ROI / income-per-hour.
    sell_venue: str = "jita_sell"     # "jita_sell" | "cj_sell"
    freight_per_unit: float = 0.0
    # Candidate universe (broad sweep + category filters).
    include_reaction_products: bool = True
    include_t2_components: bool = True
    reaction_group_ids: List[int] = []
    t2_group_ids: List[int] = []
    batch_runs: int = 10              # runs of each candidate's blueprint per analysed batch
    max_candidates: int = 50
    max_depth: int = 8
    # Characters: producer drives job-time skills; seller sets sales tax / broker fee.
    produce_character_id: Optional[int] = None
    sell_character_id: Optional[int] = None
    # On-demand Monte-Carlo only (POST /candidate/{id}/simulate); ignored by /sweep.
    sim: Optional[SimParamsIn] = None


def _facilities(body: ReactionSweepRequest, db: Session, user_id: int):
    """Reuse the calculator's facility builder (rigs, can_man/can_react by type)."""
    fac_body = ChainCalcRequest(product_type_id=0, structures=body.structures,
                                me_pct=body.me_pct, te_pct=body.te_pct)
    return _build_facilities(fac_body, db, user_id)


def _reaction_subnode_ids(target_id: int, tree: dict) -> set[int]:
    """Nodes below the target that are produced ONLY by a reaction — the intermediates a
    component can either build from scratch or buy."""
    return {tid for tid, nd in tree.items()
            if tid != target_id and nd.get("recipes")
            and all(rc["activity"] == REACTION for rc in nd["recipes"])}


def _build_chain(target_id: int, qty: int, tree: dict, buy_prices, adj, facilities,
                 tm_man: float, tm_react: float):
    return from_bom(target_id, qty, tree, buy_prices, adj, facilities,
                    time_mult_man=tm_man, time_mult_react=tm_react)


def _scratch_request(target_id, qty, tree, buy_prices, adj, facilities, tm_man, tm_react):
    """From-scratch build: force-make the target AND every reaction node (down to raw goo)."""
    req = _build_chain(target_id, qty, tree, buy_prices, adj, facilities, tm_man, tm_react)
    make_ids = {target_id} | _reaction_subnode_ids(target_id, tree)
    for tid in make_ids:
        n = req.nodes.get(tid)
        if n and n.recipes:
            req.nodes[tid] = replace(n, buy_price=None)
    return req


def _bought_request(target_id, qty, tree, buy_prices, adj, facilities, tm_man, tm_react):
    """Bought-reactions variant: force-make the target, force-BUY every (buyable) reaction
    intermediate. Returns None when no reaction intermediate can be bought."""
    req = _build_chain(target_id, qty, tree, buy_prices, adj, facilities, tm_man, tm_react)
    n = req.nodes.get(target_id)
    if n and n.recipes:
        req.nodes[target_id] = replace(n, buy_price=None)
    any_bought = False
    for tid in _reaction_subnode_ids(target_id, tree):
        m = req.nodes.get(tid)
        if m and m.recipes and m.buy_price is not None:
            req.nodes[tid] = replace(m, recipes=())
            any_bought = True
    return req if any_bought else None


def _candidate_out(r: planner.CandidateResult) -> dict:
    svb = None
    if r.scratch_vs_bought is not None:
        s = r.scratch_vs_bought
        svb = {"cheaper": s.cheaper, "scratch_cost": float(s.scratch_cost),
               "bought_cost": float(s.bought_cost), "delta": float(s.delta)}
    return {
        "type_id": r.type_id, "name": r.name, "target_qty": r.target_qty,
        "decision": r.decision,
        "unit_make_cost": float(r.unit_make_cost), "total_make_cost": float(r.total_make_cost),
        "unit_sell": float(r.unit_sell), "revenue": float(r.revenue), "profit": float(r.profit),
        "roi": float(r.roi),
        "total_time_s": r.total_time_s, "react_time_s": r.react_time_s, "man_time_s": r.man_time_s,
        "isk_per_hour": float(r.isk_per_hour), "isk_per_slot_hour": float(r.isk_per_slot_hour),
        "runs_by_activity": {str(k): v for k, v in r.runs_by_activity.items()},
        "total_stages": r.total_stages, "peak_man": r.peak_man, "peak_react": r.peak_react,
        "blueprints": [
            {"type_id": b.type_id, "name": b.name, "activity": b.activity, "runs": b.runs,
             "jobs": b.jobs, "qty_out": b.qty_out, "is_component": b.is_component,
             "batch_size": b.batch_size, "batches": b.batches}
            for b in r.blueprints
        ],
        "scratch_vs_bought": svb,
    }


def _slot_out(sf: slot_fill.SlotFillResult) -> dict:
    return {
        "status": sf.status, "note": sf.note,
        "total_profit": sf.total_profit, "total_isk_per_hour": sf.total_isk_per_hour,
        "react_seconds_used": sf.react_seconds_used, "man_seconds_used": sf.man_seconds_used,
        "react_capacity_s": sf.react_capacity_s, "man_capacity_s": sf.man_capacity_s,
        "react_util": round(sf.react_util, 4), "man_util": round(sf.man_util, 4),
        "chosen": [
            {"type_id": p.type_id, "name": p.name, "count": p.count,
             "react_seconds": p.react_seconds, "man_seconds": p.man_seconds,
             "profit": p.profit, "isk_per_hour": p.isk_per_hour}
            for p in sf.chosen
        ],
    }


@router.post("/sweep")
async def sweep(body: ReactionSweepRequest,
                current_user: UserDB = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """Analyse the candidate universe and return ROI-ranked candidates + a slot-fill plan."""
    max_n = max(1, min(body.max_candidates, MAX_SWEEP_CANDIDATES))
    eve_db = EveSessionLocal()
    try:
        candidates_meta: list[dict] = []
        if body.include_reaction_products:
            candidates_meta += eve_repo.reaction_products(eve_db, group_ids=body.reaction_group_ids or None)
        if body.include_t2_components:
            candidates_meta += eve_repo.manufactured_products_by_meta(
                eve_db, group_ids=body.t2_group_ids or None)
        # de-dup (a product could be enumerated twice) and cap.
        seen: set[int] = set()
        metas = []
        for m in candidates_meta:
            if m["type_id"] in seen:
                continue
            seen.add(m["type_id"])
            metas.append(m)
        truncated = len(metas) > max_n
        metas = metas[:max_n]
        if not metas:
            raise HTTPException(400, "No candidates match the selected filters")

        trees = {m["type_id"]: eve_repo.bom_tree(eve_db, m["type_id"], body.max_depth) for m in metas}
    finally:
        eve_db.close()

    # Keep only candidates whose target is actually buildable.
    metas = [m for m in metas if trees[m["type_id"]].get(m["type_id"], {}).get("recipes")]
    if not metas:
        raise HTTPException(400, "No buildable candidate in the selected filters")

    union_ids = sorted({tid for m in metas for tid in trees[m["type_id"]]})
    target_ids = [m["type_id"] for m in metas]
    eff_region_ids = body.region_ids if body.region_ids else [body.region_id]

    try:
        adj = market.esi_adjusted_prices()
    except Exception:
        adj = {}

    region_data = {rid: _region_two_sided(rid, union_ids) for rid in eff_region_ids}
    cj_data = await _cj_two_sided(union_ids) if body.include_cj else {}

    group_name_of = {tid: trees[m["type_id"]].get(tid, {}).get("group_name")
                     for m in metas for tid in trees[m["type_id"]]}
    rules = [{"group": r.group, "side": r.side} for r in body.price_rules]
    buy_prices, _src, _flags = _resolve_acquire_prices(
        union_ids, eff_region_ids, region_data, cj_data, adj, SCAM_RATIO,
        basis=body.price_basis, region_sides=body.region_sides, cj_side=body.cj_side,
        rules=rules, group_of=group_name_of, overrides={})

    # Sell side: per-target sell quote at the chosen venue.
    if body.sell_venue == "cj_sell":
        cj_sell = cj_data if cj_data else await _cj_two_sided(target_ids)
        sell_price = {tid: (cj_sell.get(tid) or {}).get("sell") for tid in target_ids}
    else:
        sell_two = (region_data.get(JITA_FORGE_REGION)
                    or _region_two_sided(JITA_FORGE_REGION, target_ids))
        sell_price = {tid: (sell_two.get(tid) or {}).get("sell") for tid in target_ids}

    facilities = _facilities(body, db, current_user.id)
    produce_profile = _industry_profile(db, current_user.id, body.produce_character_id)
    sell_profile = _industry_profile(db, current_user.id, body.sell_character_id)
    tm_man = produce_profile.man_time_mult if produce_profile else 1.0
    tm_react = produce_profile.react_time_mult if produce_profile else 1.0
    sales_tax = sell_profile.sales_tax_pct if sell_profile else 0.0
    broker = sell_profile.broker_fee_pct if sell_profile else 0.0

    cands: list[Candidate] = []
    for m in metas:
        tid = m["type_id"]
        tree = trees[tid]
        qty = max(1, (m.get("qty_per_run") or 1) * max(1, body.batch_runs))
        scratch = _scratch_request(tid, qty, tree, buy_prices, adj, facilities, tm_man, tm_react)
        bought = _bought_request(tid, qty, tree, buy_prices, adj, facilities, tm_man, tm_react)
        sell = SellConfig(unit_price=float(sell_price.get(tid) or 0.0),
                          sales_tax_pct=sales_tax, broker_fee_pct=broker,
                          freight_per_unit=body.freight_per_unit)
        cands.append(Candidate(tid, m["name"], sell, scratch, bought=bought))

    results, engine = rpe.analyze(cands, body.man_slots, body.react_slots)
    for r in results:
        planner.batch_components(r)

    horizon_s = int(max(1.0, body.horizon_hours) * 3600)
    slot_cands = [
        slot_fill.SlotCandidate(
            type_id=r.type_id, name=r.name, react_time_s=r.react_time_s,
            man_time_s=r.man_time_s, profit=float(r.profit), isk_per_hour=float(r.isk_per_hour))
        for r in results
    ]
    fill = slot_fill.fill_slots(slot_cands, body.man_slots, body.react_slots, horizon_s)

    scatter = [{"type_id": r.type_id, "name": r.name, "roi": float(r.roi),
                "isk_per_hour": float(r.isk_per_hour), "profit": float(r.profit)}
               for r in results]

    return {
        "candidates": [_candidate_out(r) for r in results],
        "slot_fill": _slot_out(fill),
        "scatter": scatter,
        "engine": engine,
        "analysed": len(results),
        "truncated": truncated,
        "sell_venue": body.sell_venue,
        "produce_character": _profile_out(produce_profile),
        "sell_character": _profile_out(sell_profile),
    }


@router.post("/candidate/{type_id}/simulate")
async def simulate_candidate(type_id: int, body: ReactionSweepRequest,
                             current_user: UserDB = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    """On-demand Monte-Carlo for one candidate's from-scratch build (ephemeral; reuses the
    profit-sim engine). Re-solves just this product, then runs the simulation."""
    eve_db = EveSessionLocal()
    try:
        tree = eve_repo.bom_tree(eve_db, type_id, body.max_depth)
    finally:
        eve_db.close()
    if not tree or type_id not in tree or not tree[type_id].get("recipes"):
        raise HTTPException(404, f"No build tree for type_id {type_id}")

    type_ids = list(tree)
    eff_region_ids = body.region_ids if body.region_ids else [body.region_id]
    try:
        adj = market.esi_adjusted_prices()
    except Exception:
        adj = {}
    region_data = {rid: _region_two_sided(rid, type_ids) for rid in eff_region_ids}
    cj_data = await _cj_two_sided(type_ids) if body.include_cj else {}
    group_name_of = {tid: tree.get(tid, {}).get("group_name") for tid in type_ids}
    rules = [{"group": r.group, "side": r.side} for r in body.price_rules]
    buy_prices, _src, _flags = _resolve_acquire_prices(
        type_ids, eff_region_ids, region_data, cj_data, adj, SCAM_RATIO,
        basis=body.price_basis, region_sides=body.region_sides, cj_side=body.cj_side,
        rules=rules, group_of=group_name_of, overrides={})

    if body.sell_venue == "cj_sell":
        cj_sell = cj_data if cj_data else await _cj_two_sided([type_id])
        target_sell = (cj_sell.get(type_id) or {}).get("sell")
    else:
        sell_two = region_data.get(JITA_FORGE_REGION) or _region_two_sided(JITA_FORGE_REGION, [type_id])
        target_sell = (sell_two.get(type_id) or {}).get("sell")

    facilities = _facilities(body, db, current_user.id)
    produce_profile = _industry_profile(db, current_user.id, body.produce_character_id)
    sell_profile = _industry_profile(db, current_user.id, body.sell_character_id)
    tm_man = produce_profile.man_time_mult if produce_profile else 1.0
    tm_react = produce_profile.react_time_mult if produce_profile else 1.0

    qty = max(1, (tree[type_id].get("recipes", [{}])[0].get("qty_per_run") or 1) * max(1, body.batch_runs))
    req = _scratch_request(type_id, qty, tree, buy_prices, adj, facilities, tm_man, tm_react)
    plan = solve_chain(req)
    schedule = stage_schedule(plan.jobs, body.man_slots, body.react_slots)

    sim_types = [s.type_id for s in plan.shopping_list] + [type_id]
    group_of = {tid: tree.get(tid, {}).get("category_id") for tid in tree}
    point_sell = {type_id: target_sell}
    history = sim_data.gather_history(db, current_user.id, sim_types, eff_region_ids[0],
                                      group_of=group_of, point_buy=buy_prices, point_sell=point_sell)
    params = (body.sim or SimParamsIn()).to_params()
    if (body.sim is None or body.sim.slots <= 1) and (body.man_slots + body.react_slots) > 0:
        params.slots = max(1, body.man_slots + body.react_slots)
    broker = sell_profile.broker_fee_pct if sell_profile else 0.0
    sales = sell_profile.sales_tax_pct if sell_profile else 0.0

    req_sim = profit_sim_svc.request_from_chain(
        plan, history, params, int(schedule.get("total_time_s") or 0),
        broker_fee_pct=broker, sales_tax_pct=sales, label=tree[type_id]["name"])
    result, engine = profit_sim_engine.simulate(req_sim)
    return _to_jsonable({
        "type_id": type_id, "name": tree[type_id]["name"], "engine": engine,
        "production_time_s": int(schedule.get("total_time_s") or 0),
        "metrics": asdict(result.metrics),
    })


@router.get("/candidate-universe")
def candidate_universe(current_user: UserDB = Depends(get_current_user)):
    """Group/category filters for the sweep UI: reaction-product groups and T2 groups."""
    eve_db = EveSessionLocal()
    try:
        return {
            "reaction_groups": eve_repo.industry_product_groups(eve_db, REACTION),
            "t2_groups": eve_repo.industry_product_groups(eve_db, MANUFACTURING, meta_group_id=2),
        }
    finally:
        eve_db.close()
