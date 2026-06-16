import datetime
from collections import defaultdict
from dataclasses import asdict, replace
from fractions import Fraction
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.adapters import market
from app.core.database import get_db, ProductionJob, Facility, UserDB, InventoryItem, StockMovement
from app.core.database_eve import (
    EveSessionLocal, EveType, EveRigBonus, EveGroup, EveSolarSystem,
)
from app.core.schemas import ProductionStatus, ProductionTarget, FacilityType
from app.core.security import get_current_user
from app.adapters import chain_engine
from app.repositories import eve as eve_repo
from app.services.chain import LocationParams, PlannedJob, from_bom
from app.services.costing import plan_fifo
from app.services.facility_bonus import (
    EC_COST_ROLE, EC_MATERIAL_ROLE, RigBonus, band_of, effective_bonuses,
)
from app.services.manufacturing import SCC_SURCHARGE, CalcInput, Material, run_calculation
from app.services.pricing import flag_unrealistic, resolve_price

router = APIRouter()

EC_TYPES = (FacilityType.RAITARU, FacilityType.AZBEL, FacilityType.SOTIYO)


class BlueprintInfoOut(BaseModel):
    blueprint_type_id: int
    blueprint_name: Optional[str]
    product_type_id: int
    product_name: str
    qty_per_run: int
    base_time_per_run: int
    max_production_limit: Optional[int]
    materials: list


class MaterialPrice(BaseModel):
    type_id: int
    unit_cost: float


class CalcRequest(BaseModel):
    product_type_id: int
    facility_id: Optional[int] = None
    runs: int = 1
    windows: int = 1
    me: int = 0
    te: int = 0
    bpc_cost: float = 0.0
    output_price: float = 0.0
    broker_fee_pct: float = 3.6
    system_cost_index: float = 0.0
    facility_tax_pct: float = 0.0
    structure_bonus_pct: float = 0.0
    material_bonus_pct: float = 0.0
    time_bonus_pct: float = 0.0
    material_role_pct: float = 0.0
    time_role_pct: float = 0.0
    estimated_item_value: Optional[float] = None
    material_prices: List[MaterialPrice] = []
    flag_unrealistic: bool = True
    unrealistic_ratio: float = 0.3


class JobCreate(BaseModel):
    product_type_id: int
    product_name: str
    blueprint_type_id: Optional[int] = None
    blueprint_name: Optional[str] = None
    facility_id: Optional[int] = None
    project_id: Optional[int] = None
    runs: int = 1
    windows: int = 1
    me: int = 0
    te: int = 0
    bpc_cost: float = 0.0
    paks: Optional[int] = None
    units_per_pak: Optional[int] = None
    pack_tier: Optional[str] = None
    pak_reward: Optional[float] = None
    sell_price: Optional[float] = None
    jita_sell: Optional[float] = None
    jita_buy: Optional[float] = None
    cj_sell: Optional[float] = None
    cj_buy: Optional[float] = None
    initial_contract_price: Optional[float] = None
    return_contract_price: Optional[float] = None
    status: ProductionStatus = ProductionStatus.PLANNING
    target: Optional[ProductionTarget] = None
    place: Optional[str] = None
    date_planned: Optional[datetime.datetime] = None
    date_released: Optional[datetime.datetime] = None
    code: Optional[str] = None
    contract_code: Optional[str] = None
    note: Optional[str] = None
    calc_snapshot: Optional[dict] = None


class JobUpdate(BaseModel):
    facility_id: Optional[int] = None
    project_id: Optional[int] = None
    runs: Optional[int] = None
    windows: Optional[int] = None
    me: Optional[int] = None
    te: Optional[int] = None
    bpc_cost: Optional[float] = None
    paks: Optional[int] = None
    units_per_pak: Optional[int] = None
    pack_tier: Optional[str] = None
    pak_reward: Optional[float] = None
    sell_price: Optional[float] = None
    jita_sell: Optional[float] = None
    jita_buy: Optional[float] = None
    cj_sell: Optional[float] = None
    cj_buy: Optional[float] = None
    initial_contract_price: Optional[float] = None
    return_contract_price: Optional[float] = None
    status: Optional[ProductionStatus] = None
    target: Optional[ProductionTarget] = None
    place: Optional[str] = None
    date_planned: Optional[datetime.datetime] = None
    date_released: Optional[datetime.datetime] = None
    code: Optional[str] = None
    contract_code: Optional[str] = None
    note: Optional[str] = None
    calc_snapshot: Optional[dict] = None


class JobOut(BaseModel):
    id: int
    user_id: int
    project_id: Optional[int]
    facility_id: Optional[int]
    blueprint_type_id: Optional[int]
    blueprint_name: Optional[str]
    product_type_id: int
    product_name: str
    runs: int
    windows: Optional[int] = 1
    me: int
    te: int
    bpc_cost: Optional[float]
    paks: Optional[int]
    units_per_pak: Optional[int]
    pack_tier: Optional[str]
    pak_reward: Optional[float]
    sell_price: Optional[float]
    jita_sell: Optional[float]
    jita_buy: Optional[float]
    cj_sell: Optional[float]
    cj_buy: Optional[float]
    initial_contract_price: Optional[float]
    return_contract_price: Optional[float]
    calc_snapshot: Optional[dict]
    status: ProductionStatus
    target: Optional[ProductionTarget]
    place: Optional[str]
    date_planned: Optional[datetime.datetime]
    date_released: Optional[datetime.datetime]
    code: Optional[str]
    contract_code: Optional[str]
    note: Optional[str]
    created_at: datetime.datetime
    updated_at: Optional[datetime.datetime]

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/blueprint", response_model=BlueprintInfoOut)
async def get_blueprint_info(
        product_type_id: int,
        current_user: UserDB = Depends(get_current_user),
):
    """
    Given a product type_id, return the manufacturing blueprint info + base materials.
    """
    eve_db = EveSessionLocal()
    try:
        bp = eve_repo.blueprint_for_product(eve_db, product_type_id)
        if not bp:
            raise HTTPException(404, f"No manufacturing blueprint found for type_id {product_type_id}")

        bp_type_id = bp.blueprint_type_id
        base_time = eve_repo.base_time(eve_db, bp_type_id)
        materials = eve_repo.materials(eve_db, bp_type_id)
        names = eve_repo.type_names(eve_db, [bp_type_id, product_type_id])

        return BlueprintInfoOut(
            blueprint_type_id=bp_type_id,
            blueprint_name=names.get(bp_type_id),
            product_type_id=product_type_id,
            product_name=names.get(product_type_id, str(product_type_id)),
            qty_per_run=bp.qty_per_run,
            base_time_per_run=base_time,
            max_production_limit=eve_repo.max_production_limit(eve_db, bp_type_id),
            materials=materials,
        )
    finally:
        eve_db.close()


@router.post("/calculate")
async def calculate(
        body: CalcRequest,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Full manufacturing cost calculation."""
    eve_db = EveSessionLocal()
    try:
        bp = eve_repo.blueprint_for_product(eve_db, body.product_type_id)
        if not bp:
            raise HTTPException(404, "Blueprint not found")

        bp_type_id = bp.blueprint_type_id
        qty_per_run = bp.qty_per_run
        base_time = eve_repo.base_time(eve_db, bp_type_id)
        base_mats = eve_repo.materials(eve_db, bp_type_id)

        product_name = eve_repo.type_names(eve_db, [body.product_type_id]).get(
            body.product_type_id, str(body.product_type_id))

    finally:
        eve_db.close()

    price_map = {p.type_id: p.unit_cost for p in body.material_prices}

    try:
        adj = market.esi_adjusted_prices()
    except Exception:
        adj = {}

    # Drop scam / unrealistically-low material prices before costing.
    price_flags: dict[int, dict] = {}
    if body.flag_unrealistic and adj:
        price_map, price_flags = flag_unrealistic(price_map, adj, ratio=body.unrealistic_ratio)

    materials = [
        {**m, "unit_cost": price_map.get(m["type_id"], 0.0)}
        for m in base_mats
    ]

    eiv = body.estimated_item_value
    if not eiv or eiv <= 0:
        computed = sum((m["base_qty"] * body.runs) * adj.get(m["type_id"], 0.0) for m in base_mats)
        eiv = computed if computed > 0 else None

    sci = body.system_cost_index
    tax = body.facility_tax_pct
    s_bonus = body.structure_bonus_pct
    mat_role = body.material_role_pct
    time_role = body.time_role_pct
    if body.facility_id:
        f = db.query(Facility).filter(Facility.id == body.facility_id).first()
        if f:
            if sci == 0.0 and f.system_cost_index:
                sci = f.system_cost_index
            if tax == 0.0 and f.tax:
                tax = f.tax
            if f.facility_type in EC_TYPES:
                if mat_role == 0.0:
                    mat_role = EC_MATERIAL_ROLE
                if s_bonus == 0.0:
                    s_bonus = max(EC_COST_ROLE, f.cost_bonus or 0.0)
            elif s_bonus == 0.0 and f.cost_bonus:
                s_bonus = f.cost_bonus

    inp = CalcInput(
        product_name=product_name,
        product_qty_per_run=qty_per_run,
        runs=body.runs,
        me=body.me,
        te=body.te,
        base_time_per_run=base_time,
        materials=[
            Material(type_id=m["type_id"], name=m["name"],
                     base_qty=m["base_qty"], unit_cost=m["unit_cost"])
            for m in materials
        ],
        output_price=body.output_price,
        bpc_cost=body.bpc_cost,
        broker_fee_pct=body.broker_fee_pct,
        system_cost_index=sci,
        facility_tax_pct=tax,
        structure_bonus_pct=s_bonus,
        estimated_item_value=eiv,
        material_bonus_pct=body.material_bonus_pct,
        time_bonus_pct=body.time_bonus_pct,
        material_role_pct=mat_role,
        time_role_pct=time_role,
        windows=body.windows,
    )
    result = asdict(run_calculation(inp))
    result["price_flags"] = {str(t): fl for t, fl in price_flags.items()}
    return result


# Recursive make-vs-buy chain + slot assignment

class ChainStructure(BaseModel):
    """One of the user's facilities for multi-location building. ``place_id`` is the
    Facility id, so the backend can load its rigs for per-node ME/TE/cost."""
    place_id: int
    name: str = ""
    system_cost_index: float = 0.0      # fraction, e.g. 0.0593
    facility_tax_pct: float = 0.0
    structure_discount_pct: float = 0.0
    man_lines: int = 0                   # 0 = can't run manufacturing here
    react_lines: int = 0                 # 0 = can't run reactions here


class ChainCalcRequest(BaseModel):
    product_type_id: int
    qty: int = 1
    region_id: int = 10000002
    region_ids: List[int] = []     # multi-region: take min price across all; falls back to region_id
    include_cj: bool = False       # also fetch C-J6MT prices and take min (slow: 1 scrape/type)
    price_basis: str = "buy"
    facility_id: Optional[int] = None
    place_id: int = 0
    place_name: str = ""
    me_pct: float = 0.0
    te_pct: float = 0.0
    system_cost_index: float = 0.0
    facility_tax_pct: float = 0.0
    structure_discount_pct: float = 0.0
    man_lines: int = 0
    react_lines: int = 0
    window_hours: float = 24.0     # deprecated/ignored — kept for old clients
    max_depth: int = 12
    price_overrides: dict[int, float] = {}
    # Scam-price guard: drop buy prices below `unrealistic_ratio` of the ESI adjusted
    # price (manual price_overrides are exempt). Set flag_unrealistic=False to disable.
    flag_unrealistic: bool = True
    unrealistic_ratio: float = 0.3
    # Nodes the user chose to skip making (force buy): their recipes are dropped so
    # the core can only buy them. Lets the chain be re-shaped from the graph.
    force_buy: List[int] = []
    # The user's facilities. When given, each makeable node is built at the cheapest
    # eligible one (the core picks per node, using that facility's rigs).
    structures: List[ChainStructure] = []


def _fnum(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _market_buy_prices(region_id: int, type_ids: list[int], basis: str) -> dict[int, Optional[float]]:
    """Per-type acquire cost from Fuzzwork aggregates (5% percentile, side by basis)."""
    agg = market.fuzzwork_aggregates_or_empty(region_id, type_ids)
    side = "buy" if basis == "buy" else "sell"
    fallback = "max" if side == "buy" else "min"
    out: dict[int, Optional[float]] = {}
    for tid in type_ids:
        s = (agg.get(str(tid)) or {}).get(side) or {}
        val = s.get("percentile") or s.get(fallback)
        out[tid] = float(val) if val else None
    return out


def _region_two_sided(region_id: int, type_ids: list[int]) -> dict[int, dict]:
    """Per-type ``{'buy','sell'}`` acquire prices from one region's Fuzzwork
    aggregate — both sides from a single fetch, so the scam-price fallback can swap
    sides or regions without extra calls."""
    agg = market.fuzzwork_aggregates_or_empty(region_id, type_ids)
    out: dict[int, dict] = {}
    for tid in type_ids:
        s = agg.get(str(tid)) or {}
        b = s.get("buy") or {}
        se = s.get("sell") or {}
        out[tid] = {
            "buy": _fnum(b.get("percentile") or b.get("max")),
            "sell": _fnum(se.get("percentile") or se.get("min")),
        }
    return out


def _job_dict(j: PlannedJob) -> dict:
    d = asdict(j)
    d["make_cost"] = j.make_cost
    d["buy_fallback_total"] = j.buy_fallback_total
    return d


def _plan_dict(plan) -> dict:
    return {
        "target_type_id": plan.target_type_id,
        "target_qty": plan.target_qty,
        "unit_cost": plan.unit_cost,
        "total_cost": plan.total_cost,
        "decisions": {str(t): asdict(d) for t, d in plan.decisions.items()},
        "jobs": [_job_dict(j) for j in plan.jobs],
        "shopping_list": [asdict(s) for s in plan.shopping_list],
    }


def _to_jsonable(x):
    """The exact core returns Fractions; collapse them to float at the API edge."""
    if isinstance(x, Fraction):
        return float(x)
    if isinstance(x, dict):
        return {k: _to_jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_to_jsonable(v) for v in x]
    return x


def _facility_location(s: ChainStructure, f, rigs, band: str,
                       me_pct: float, te_pct: float) -> LocationParams:
    """Turn one of the user's facilities into a chain LocationParams.

    Costs/SCI/tax come from the structure payload; ME/TE/cost *rigs* come from the
    facility's fitted rigs (``rigs``) and are applied per node by the core. The
    global me_pct/te_pct are the manual base the rigs multiply onto.
    """
    is_ec = bool(f and f.facility_type in EC_TYPES)
    return LocationParams(
        place_id=s.place_id,
        place_name=s.name or (getattr(f, "name", None) if f else None) or f"struct {s.place_id}",
        me_mult=1 - me_pct / 100, te_mult=1 - te_pct / 100,
        sci=s.system_cost_index, tax=s.facility_tax_pct / 100, scc=SCC_SURCHARGE,
        struct_discount=s.structure_discount_pct / 100,
        man_lines=s.man_lines, react_lines=s.react_lines,
        rigs=tuple(rigs), band=band, is_ec=is_ec,
        can_man=s.man_lines > 0, can_react=s.react_lines > 0,
    )


def _chain_assignment(plan, facilities: list[LocationParams]) -> dict:
    """In-house/factory summary derived straight from the core's per-job facility
    choice — no window, no bounce (make-vs-buy was already decided by cost, and each
    job already carries its cheapest facility's place_id/place_name).

    Shape matches the old AssignmentResult the UI consumes (in_house/bought/usage…),
    so the Chain tab needs no special-casing.
    """
    man_lines = {f.place_id: f.man_lines for f in facilities}
    react_lines = {f.place_id: f.react_lines for f in facilities}
    in_house: list[dict] = []
    by_line: dict[tuple, dict] = defaultdict(lambda: {"jobs": 0, "used_s": 0})
    captured = 0.0
    for i, j in enumerate(plan.jobs):
        in_house.append({
            "job_index": i, "type_id": j.type_id, "name": j.name,
            "place_id": j.place_id, "place_name": j.place_name, "slot_kind": j.slot_kind,
            "in_house": True, "time_s": j.time_s, "cost": round(float(j.make_cost), 2),
        })
        fb = j.buy_fallback_total
        if fb is not None:
            captured += max(0.0, float(fb) - float(j.make_cost))
        g = by_line[(j.place_id, j.slot_kind)]
        g["jobs"] += 1
        g["used_s"] += j.time_s
    usage = [
        {"place_id": pid, "slot_kind": kind,
         "lines": (man_lines if kind == "manufacturing" else react_lines).get(pid, 0),
         "capacity_s": 0, "used_s": g["used_s"], "jobs": g["jobs"], "forced_s": 0}
        for (pid, kind), g in by_line.items()
    ]
    return {
        "status": "optimal", "in_house": in_house, "bought": [],
        "total_cost": round(float(plan.total_cost), 2),
        "savings_captured": round(captured, 2), "savings_forfeited": 0.0,
        "usage": usage, "note": "",
    }


def _build_facilities(body: "ChainCalcRequest", db: Session, user_id: int) -> list[LocationParams]:
    """Locations the chain may build at: the user's selected facilities (each loaded
    with its rigs for per-node ME/TE/cost), or a single manual/default location when
    none are chosen. The default location stays rig-free so its behaviour is unchanged.
    """
    if body.structures:
        fac_ids = [s.place_id for s in body.structures]
        facs = {f.id: f for f in db.query(Facility).filter(
            Facility.id.in_(fac_ids or [-1]), Facility.user_id == user_id).all()}
        eve_db = EveSessionLocal()
        try:
            out = []
            for s in body.structures:
                f = facs.get(s.place_id)
                rigs, band, _sec = _facility_rig_context(eve_db, f) if f else ([], "null", None)
                out.append(_facility_location(s, f, rigs, band, body.me_pct, body.te_pct))
            return out
        finally:
            eve_db.close()

    # single facility (facility_id) or pure-manual default — one location, both activities
    sci, tax_pct, disc_pct = body.system_cost_index, body.facility_tax_pct, body.structure_discount_pct
    place_id, place_name = body.place_id, body.place_name
    rigs, band, is_ec = [], "null", False
    if body.facility_id:
        f = db.query(Facility).filter(Facility.id == body.facility_id,
                                      Facility.user_id == user_id).first()
        if f:
            place_id = place_id or f.id
            place_name = place_name or getattr(f, "name", None) or f.facility_type.value
            if sci == 0.0 and f.system_cost_index:
                sci = f.system_cost_index
            if tax_pct == 0.0 and f.tax:
                tax_pct = f.tax
            if disc_pct == 0.0 and f.cost_bonus:
                disc_pct = f.cost_bonus
            is_ec = f.facility_type in EC_TYPES
            eve_db = EveSessionLocal()
            try:
                rigs, band, _sec = _facility_rig_context(eve_db, f)
            finally:
                eve_db.close()
    return [LocationParams(
        place_id=place_id or 1, place_name=place_name or "facility",
        me_mult=1 - body.me_pct / 100, te_mult=1 - body.te_pct / 100,
        sci=sci, tax=tax_pct / 100, scc=SCC_SURCHARGE, struct_discount=disc_pct / 100,
        man_lines=body.man_lines, react_lines=body.react_lines,
        rigs=tuple(rigs), band=band, is_ec=is_ec,
    )]


@router.post("/calculate-chain")
async def calculate_chain(
        body: ChainCalcRequest,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """
    Full recursive make-vs-buy over the product's whole build tree (manufacturing
    + reactions). With facilities selected, every makeable node is assigned to the
    *cheapest* eligible facility by the core itself (each facility's rigs/ME/TE/cost
    applied per node); no time window — make-vs-buy is decided purely on cost.
    ``force_buy`` drops a node's recipes so the user can skip making it. One pass
    through the two engines; see app.services.chain.
    """
    eve_db = EveSessionLocal()
    try:
        tree = eve_repo.bom_tree(eve_db, body.product_type_id, body.max_depth)
    finally:
        eve_db.close()
    if not tree or body.product_type_id not in tree:
        raise HTTPException(404, f"No build tree for type_id {body.product_type_id}")
    if not tree[body.product_type_id]["recipes"]:
        raise HTTPException(400, "Target product has no manufacturing/reaction recipe")

    type_ids = list(tree)
    eff_region_ids = body.region_ids if body.region_ids else [body.region_id]

    try:
        adj = market.esi_adjusted_prices()
    except Exception:
        adj = {}

    # Both market sides from every selected region (one fetch each), plus optional C-J.
    region_data = {rid: _region_two_sided(rid, type_ids) for rid in eff_region_ids}
    cj_data: dict[int, dict] = {}
    if body.include_cj:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=8) as ex:
            cj_results = await asyncio.gather(
                *[loop.run_in_executor(ex, market.gnf_local, tid) for tid in type_ids]
            )
        for tid, p in zip(type_ids, cj_results):
            if p:
                cj_data[tid] = {"buy": _fnum(p.get("buy")), "sell": _fnum(p.get("sell"))}

    overrides = {int(k): float(v) for k, v in body.price_overrides.items()}
    ratio = body.unrealistic_ratio if body.flag_unrealistic else 0.0

    # Per type: cheapest *realistic* price — another region or the sell side beats a
    # scam buy order before we ever fall back to the ESI adjusted price.
    buy_prices: dict[int, Optional[float]] = {}
    price_source: dict[int, object] = {}     # type_id -> region_id / "C-J6MT" / "adjusted" / "override"
    price_flags: dict[int, dict] = {}
    for tid in type_ids:
        if tid in overrides:
            buy_prices[tid] = overrides[tid]
            price_source[tid] = "override"
            continue
        buy_c = [(region_data[rid][tid]["buy"], rid) for rid in eff_region_ids]
        sell_c = [(region_data[rid][tid]["sell"], rid) for rid in eff_region_ids]
        if tid in cj_data:
            buy_c.append((cj_data[tid]["buy"], "C-J6MT"))
            sell_c.append((cj_data[tid]["sell"], "C-J6MT"))
        price, src, flag = resolve_price(buy_c, sell_c, adj.get(tid), ratio, body.price_basis)
        buy_prices[tid] = price
        if src is not None:
            price_source[tid] = src
        if flag:
            price_flags[tid] = flag

    facilities = _build_facilities(body, db, current_user.id)
    req = from_bom(body.product_type_id, body.qty, tree, buy_prices, adj, facilities)

    # Skip-making (force buy): drop those nodes' recipes so the core can only buy
    # them. Guard nodes that have nothing to buy — leave them makeable.
    forced_skipped: list[int] = []
    for tid in set(body.force_buy):
        n = req.nodes.get(tid)
        if not n or not n.recipes:
            continue
        if n.buy_price is None:
            forced_skipped.append(tid)
            continue
        req.nodes[tid] = replace(n, recipes=())

    plan, engine = chain_engine.solve(req)   # native Haskell core, falls back to Python

    return _to_jsonable({
        "plan": _plan_dict(plan),
        "assignment": _chain_assignment(plan, facilities),
        "final_cost": round(float(plan.total_cost), 2),
        "engine": engine,
        "multi_location": len(facilities) > 1,
        "price_basis": body.price_basis,
        "price_source": {str(t): src for t, src in price_source.items()},
        "price_flags": {str(t): fl for t, fl in price_flags.items()},
        "force_buy_skipped": forced_skipped,
    })


# Facility rig bonuses

def _facility_rig_context(eve_db, f) -> tuple[list[RigBonus], str, Optional[float]]:
    """A facility's fitted rigs (as RigBonus) + its system security band + security.

    One SDE round-trip; reused by the /facility-bonuses endpoint and the chain
    wiring so a facility's rigs are read the same way everywhere.
    """
    rig_ids = [r for r in (f.rig1_type_id, f.rig2_type_id, f.rig3_type_id) if r]
    sec = None
    if f.system_name:
        sysrow = eve_db.query(EveSolarSystem).filter(
            EveSolarSystem.solar_system_name.ilike(f.system_name.strip())
        ).first()
        sec = sysrow.security if sysrow else None

    rig_types = {t.type_id: t for t in
                 eve_db.query(EveType).filter(EveType.type_id.in_(rig_ids or [-1])).all()}
    rig_bonuses = {rb.type_id: rb for rb in
                   eve_db.query(EveRigBonus).filter(EveRigBonus.type_id.in_(rig_ids or [-1])).all()}
    rigs: list[RigBonus] = []
    for rid in rig_ids:
        t = rig_types.get(rid)
        name = t.type_name if t else str(rid)
        rb = rig_bonuses.get(rid)
        if rb:
            rigs.append(RigBonus(rid, name, rb.me_bonus, rb.te_bonus, rb.cost_bonus,
                                 rb.hisec_mod, rb.lowsec_mod, rb.nullsec_mod))
        else:
            rigs.append(RigBonus(rid, name, has_industry_bonus=False))
    return rigs, band_of(sec), sec


@router.get("/facility-bonuses")
async def facility_bonuses(
        facility_id: int,
        product_type_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """
    Effective ME/TE/cost bonus from a facility's rigs for a given product,
    scaled by the structure system's security band. Auto-skips rigs that
    don't apply to the product's category.
    """
    f = db.query(Facility).filter(Facility.id == facility_id, Facility.user_id == current_user.id).first()
    if not f:
        raise HTTPException(404, "Facility not found")

    eve_db = EveSessionLocal()
    try:
        rigs, band, sec = _facility_rig_context(eve_db, f)

        prod = eve_db.query(EveType).filter(EveType.type_id == product_type_id).first()
        grp = eve_db.query(EveGroup).filter(EveGroup.group_id == prod.group_id).first() if prod else None
        cat_id = grp.category_id if grp else None
        group_name = grp.group_name if grp else None

        eff = effective_bonuses(rigs, band, cat_id, group_name)

        is_ec = f.facility_type in EC_TYPES
        structure_role = {
            "name": f.facility_type.value if is_ec else None,
            "material_pct": EC_MATERIAL_ROLE if is_ec else 0.0,
            "time_pct": 0.0,
            "cost_pct": EC_COST_ROLE if is_ec else 0.0,
        }

        return {
            "facility_id": facility_id,
            "facility_type": f.facility_type.value,
            "security": sec, "band": band,
            "product_category_id": cat_id, "product_group": group_name,
            "total_me_pct": round(eff.me_pct, 2),
            "total_te_pct": round(eff.te_pct, 2),
            "total_cost_pct": round(eff.cost_pct, 2),
            "structure_role": structure_role,
            "rigs": eff.rigs,
        }
    finally:
        eve_db.close()


# Production Job CRUD

@router.get("/jobs", response_model=List[JobOut])
async def list_jobs(
        project_id: Optional[int] = None,
        job_status: Optional[ProductionStatus] = None,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    q = db.query(ProductionJob).filter(ProductionJob.user_id == current_user.id)
    if project_id:  q = q.filter(ProductionJob.project_id == project_id)
    if job_status:  q = q.filter(ProductionJob.status == job_status)
    return q.order_by(ProductionJob.date_planned.desc()).all()


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
        body: JobCreate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    j = ProductionJob(user_id=current_user.id, **body.model_dump())
    db.add(j)
    db.commit()
    db.refresh(j)
    return j


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(
        job_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    return _job_or_404(db, job_id, current_user.id)


@router.patch("/jobs/{job_id}", response_model=JobOut)
async def update_job(
        job_id: int,
        body: JobUpdate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    j = _job_or_404(db, job_id, current_user.id)
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(j, field, val)
    j.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(j)
    return j


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
        job_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    j = _job_or_404(db, job_id, current_user.id)
    db.delete(j)
    db.commit()


# Inventory LIFO/FIFO analysis

@router.get("/inventory-analysis")
async def inventory_analysis(
        method: str = "FIFO",  # FIFO | LIFO
        project_id: Optional[int] = None,
        organisation_id: Optional[int] = None,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """
    Cost-basis analysis of inventory using FIFO or LIFO costing.
    Groups items by eve_type_id (or name), returns weighted average cost and
    total value using the selected inventory costing method.
    """
    from app.core.database import InventoryItem, Projects

    q = db.query(InventoryItem).filter(InventoryItem.user_id == current_user.id)
    if project_id:
        q = q.filter(InventoryItem.project_id == project_id)
    elif organisation_id:
        proj_ids = [pid for (pid,) in db.query(Projects.id).filter(Projects.organisation_id == organisation_id).all()]
        q = q.filter(InventoryItem.project_id.in_(proj_ids or [-1]))

    all_items = q.order_by(
        InventoryItem.eve_type_id,
        InventoryItem.created_at.asc() if method.upper() == "FIFO"
        else InventoryItem.created_at.desc(),
    ).all()

    # group by eve_type_id (fall back to name if no type_id)
    groups: dict[str, list] = {}
    for item in all_items:
        key = str(item.eve_type_id) if item.eve_type_id else f"name:{item.name}"
        groups.setdefault(key, []).append(item)

    result = []
    for key, items in groups.items():
        total_qty = sum(i.quantity for i in items)
        priced = [i for i in items if i.price]
        total_value = sum(i.quantity * (i.price or 0) for i in items)
        avg_cost = total_value / total_qty if total_qty else 0

        result.append({
            "key": key,
            "eve_type_id": items[0].eve_type_id,
            "name": items[0].name,
            "method": method.upper(),
            "total_qty": total_qty,
            "lots": len(items),
            "priced_lots": len(priced),
            "avg_cost_isk": round(avg_cost, 2),
            "total_value_isk": round(total_value, 2),
            "lots_detail": [
                {
                    "id": i.id,
                    "qty": i.quantity,
                    "price": i.price,
                    "place": i.place,
                    "created_at": i.created_at.isoformat() if i.created_at else None,
                }
                for i in items
            ],
        })

    return {"method": method.upper(), "items": result}


# Warehouse availability + material write-off

class MatNeed(BaseModel):
    type_id: Optional[int] = None
    name: str
    required_qty: int


class AvailabilityRequest(BaseModel):
    project_id: Optional[int] = None
    materials: List[MatNeed]


def _stock_query(db: Session, user_id: int, project_id: Optional[int]):
    """
    Scope rule: if a project is chosen, only that project's stock counts;
    if no project, only stock that is itself unassigned (project_id IS NULL).
    """
    q = db.query(InventoryItem).filter(InventoryItem.user_id == user_id)
    if project_id:
        q = q.filter(InventoryItem.project_id == project_id)
    else:
        q = q.filter(InventoryItem.project_id.is_(None))
    return q


def _match_lots(db, user_id, project_id, type_id, name):
    """Inventory lots for one material, FIFO order (oldest first)."""
    q = _stock_query(db, user_id, project_id).filter(InventoryItem.quantity > 0)
    if type_id:
        q = q.filter(InventoryItem.eve_type_id == type_id)
    else:
        q = q.filter(InventoryItem.name.ilike(name.strip()))
    return q.order_by(InventoryItem.created_at.asc()).all()


@router.post("/material-availability")
async def material_availability(
        body: AvailabilityRequest,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """How much of each material is on the warehouse (scoped), plus shortfall + avg price."""
    out = []
    for m in body.materials:
        lots = _match_lots(db, current_user.id, body.project_id, m.type_id, m.name)
        available = sum(l.quantity for l in lots)
        priced_qty = sum(l.quantity for l in lots if l.price)
        total_val = sum(l.quantity * l.price for l in lots if l.price)
        wavg = round(total_val / priced_qty, 2) if priced_qty else None
        out.append({
            "type_id": m.type_id,
            "name": m.name,
            "required": m.required_qty,
            "available": available,
            "shortfall": max(0, m.required_qty - available),
            "warehouse_unit_price": wavg,
        })
    return {"project_id": body.project_id, "materials": out}


@router.post("/jobs/{job_id}/issue")
async def issue_job_materials(
        job_id: int,
        force: bool = False,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """
    Consume the job's materials from the warehouse (FIFO) and record a stock
    movement per material. Scope follows the job's project. Sets status to
    'In Progress'. Refuses to run twice unless force=True.
    """
    job = _job_or_404(db, job_id, current_user.id)

    snap = job.calc_snapshot or {}
    materials = snap.get("materials") or []
    if not materials:
        raise HTTPException(400, "Job has no material snapshot to consume")

    already = (
        db.query(StockMovement)
        .filter(StockMovement.production_job_id == job.id, StockMovement.direction == "out")
        .first()
    )
    if already and not force:
        raise HTTPException(400, "Materials already issued for this job (use force=true to repeat)")

    results = []
    grand_total = 0.0
    for m in materials:
        need = int(m.get("adj_qty") or 0)
        if need <= 0:
            continue
        lots = _match_lots(db, current_user.id, job.project_id, m.get("type_id"), m.get("name", ""))

        # pure FIFO plan → then apply the warehouse mutation here
        plan = plan_fifo([(lot.quantity, lot.price) for lot in lots], need)
        consumed = plan.consumed
        cost = plan.cost
        for line in plan.lines:
            lot = lots[line.index]
            lot.quantity -= line.take
            if lot.quantity == 0:
                db.delete(lot)

        if consumed > 0:
            mv = StockMovement(
                user_id=current_user.id,
                project_id=job.project_id,
                production_job_id=job.id,
                eve_type_id=m.get("type_id"),
                name=m.get("name", ""),
                quantity=consumed,
                direction="out",
                unit_cost=round(cost / consumed, 2) if consumed else None,
                total_cost=round(cost, 2),
                reason=f"PAK #{job.id} issue — {job.product_name}",
            )
            db.add(mv)
            grand_total += cost

        results.append({
            "name": m.get("name", ""),
            "required": need,
            "consumed": consumed,
            "shortfall": max(0, need - consumed),
            "cost": round(cost, 2),
        })

    # recompute the real unit cost from what was actually consumed (warehouse FIFO)
    snap = dict(job.calc_snapshot or {})
    out_qty = (snap.get("output") or {}).get("quantity") or 0
    bpc = snap.get("bpc_cost") or 0
    install = (snap.get("job_cost") or {}).get("net_install_cost") or 0
    actual_total = grand_total + bpc + install
    snap["actual"] = {
        "material_cost": round(grand_total, 2),
        "total_cost": round(actual_total, 2),
        "unit_cost": round(actual_total / out_qty, 2) if out_qty else None,
    }
    job.calc_snapshot = snap  # reassign new dict → JSON column marked dirty

    if job.status in (ProductionStatus.PLANNING, ProductionStatus.PREPARING):
        job.status = ProductionStatus.IN_PROGRESS
    job.updated_at = datetime.datetime.utcnow()
    db.commit()

    return {
        "job_id": job.id,
        "total_cost": round(grand_total, 2),
        "actual_unit_cost": snap["actual"]["unit_cost"],
        "materials": results,
        "shortfalls": [r for r in results if r["shortfall"] > 0],
    }


class ReceiveRequest(BaseModel):
    unit_price: Optional[float] = None
    quantity: Optional[int] = None
    place: Optional[str] = None


@router.post("/jobs/{job_id}/receive")
async def receive_job_output(
        job_id: int,
        body: ReceiveRequest,
        force: bool = False,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """
    Mark a PAK received: add the produced units to inventory as OUTPUT at their
    production cost (actual if materials were issued, else planned), log an 'in'
    movement, and complete the job.
    """
    job = _job_or_404(db, job_id, current_user.id)
    snap = job.calc_snapshot or {}
    out = snap.get("output") or {}
    qty = int(body.quantity or out.get("quantity") or 0)
    if qty <= 0:
        raise HTTPException(400, "Nothing to receive (no output quantity)")

    already = (
        db.query(StockMovement)
        .filter(StockMovement.production_job_id == job.id, StockMovement.direction == "in")
        .first()
    )
    if already and not force:
        raise HTTPException(400, "Output already received for this job (use force=true to repeat)")

    # cost basis: actual (post-issue) → else planned total cost per unit
    actual = snap.get("actual") or {}
    unit = actual.get("unit_cost")
    if unit is None:
        tc = (snap.get("results") or {}).get("total_costs")
        oq = out.get("quantity")
        unit = round(tc / oq, 2) if tc and oq else None
    if body.unit_price is not None:
        unit = body.unit_price

    eve_db = EveSessionLocal()
    try:
        vol = eve_repo.type_volume(eve_db, job.product_type_id)
    finally:
        eve_db.close()

    item = InventoryItem(
        user_id=current_user.id,
        project_id=job.project_id,
        eve_type_id=job.product_type_id,
        name=job.product_name,
        volume=vol,
        quantity=qty,
        price=unit,
        place=body.place or job.place,
        flow="output",
        item_status="in_stock",
        note=f"PAK #{job.id} output",
    )
    db.add(item)
    db.add(StockMovement(
        user_id=current_user.id, project_id=job.project_id, production_job_id=job.id,
        eve_type_id=job.product_type_id, name=job.product_name,
        quantity=qty, direction="in",
        unit_cost=unit, total_cost=round(unit * qty, 2) if unit else None,
        reason=f"PAK #{job.id} received — {job.product_name}",
    ))

    job.status = ProductionStatus.COMPLETED
    job.date_released = datetime.datetime.utcnow()
    job.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(item)

    return {"job_id": job.id, "received_qty": qty, "unit_cost": unit, "inventory_id": item.id}


@router.get("/jobs/{job_id}/movements")
async def job_movements(
        job_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Stock movements recorded against a job (audit trail)."""
    _job_or_404(db, job_id, current_user.id)
    rows = (
        db.query(StockMovement)
        .filter(StockMovement.production_job_id == job_id)
        .order_by(StockMovement.created_at.asc())
        .all()
    )
    return [
        {
            "id": r.id, "name": r.name, "quantity": r.quantity,
            "direction": r.direction, "unit_cost": r.unit_cost,
            "total_cost": r.total_cost, "reason": r.reason,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def _job_or_404(db: Session, job_id: int, user_id: int) -> ProductionJob:
    j = db.query(ProductionJob).filter(
        ProductionJob.id == job_id,
        ProductionJob.user_id == user_id,
    ).first()
    if not j:
        raise HTTPException(404, "Production job not found")
    return j
