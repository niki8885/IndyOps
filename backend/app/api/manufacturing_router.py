import datetime
from app.core.timeutil import utcnow
import logging
from collections import defaultdict
from dataclasses import asdict, replace
from fractions import Fraction
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.adapters import market
from app.core.database import (
    get_db, ProductionJob, ProductionStatusEvent, Facility, UserDB, InventoryItem,
    StockMovement, Blueprint, LinkedCharacter, EsiSkill, EsiStanding, EsiBlueprintCopy,
)
from app.core.database_eve import (
    EveSessionLocal, EveType, EveRigBonus, EveGroup, EveSolarSystem,
)
from app.core.schemas import ProductionStatus, ProductionTarget, FacilityType
from app.core.security import get_current_user
from app.adapters import chain_engine
from app.adapters import sim_data
from app.api import simulation_router as sim_router
from app.api.responses import ERR_400, ERR_404
from app.api.simulation_router import ScenarioRequestIn, SimParamsIn
from app.repositories import eve as eve_repo
from app.repositories import share_repo
from app.services.chain import REACTION, LocationParams, PlannedJob, from_bom
from app.services.costing import plan_fifo
from app.services.facility_bonus import (
    EC_COST_ROLE, EC_MATERIAL_ROLE, RigBonus, band_of, effective_bonuses,
)
from app.services.manufacturing import SCC_SURCHARGE, CalcInput, Material, run_calculation
from app.services import blueprints as bp_svc
from app.services import production_report_pdf
from app.services.scheduling import stage_schedule
from app.services.pricing import flag_unrealistic, resolve_sided, rule_side
from app.services import skills as skills_svc

router = APIRouter()
logger = logging.getLogger(__name__)

EC_TYPES = (FacilityType.RAITARU, FacilityType.AZBEL, FacilityType.SOTIYO)
REACTION_TYPES = (FacilityType.ATHANOR, FacilityType.TATARA)

MAX_CHAIN_QTY = 100_000
MAX_CHAIN_JOBS = 20_000


def _activity_caps(facility_type) -> tuple[bool, bool]:
    """(can_manufacture, can_react) for a facility type. Engineering complexes only
    manufacture, refineries only run reactions, 'Other' can do both. This is what
    keeps reactions off a Raitaru even if its slots are mis-configured."""
    if facility_type in REACTION_TYPES:
        return (False, True)
    if facility_type in EC_TYPES:
        return (True, False)
    return (True, True)


class BlueprintInfoOut(BaseModel):
    blueprint_type_id: int
    blueprint_name: Optional[str] = None
    product_type_id: int
    product_name: str
    qty_per_run: int
    base_time_per_run: int
    max_production_limit: Optional[int] = None
    materials: list
    activity_id: int = 1            # 1 = manufacturing, 11 = reaction
    is_reaction: bool = False


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
    # IO-22: optionally run a Monte-Carlo profit simulation on this calc and store it.
    simulate: bool = False
    project_id: Optional[int] = None
    region_id: int = 10000002        # market region for sim history (default The Forge)
    sim: Optional[SimParamsIn] = None
    # IO-23: optionally run a Scenario Simulation analysis (baseline + stress tests).
    scenarios: Optional[ScenarioRequestIn] = None
    # Character selection (LinkedCharacter.id): producer recalcs job time from skills;
    # seller sets the sell-side fees (broker fee + sales tax).
    produce_character_id: Optional[int] = None
    sell_character_id: Optional[int] = None
    # Client origin (e.g. https://host) so the server can build the reopen link for the
    # short share code it generates and stores for this build.
    share_base: Optional[str] = None
    # When reopening a shared build, the original code — so it is kept (refreshed) instead
    # of minting a new one.
    reuse_code: Optional[str] = None


class JobCreate(BaseModel):
    product_type_id: int
    product_name: str
    kind: str = "pak"                      # 'pak' (outsourced) | 'indy' (internal plan)
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
    kind: Optional[str] = "pak"
    project_id: Optional[int] = None
    facility_id: Optional[int] = None
    blueprint_type_id: Optional[int] = None
    blueprint_name: Optional[str] = None
    product_type_id: int
    product_name: str
    runs: int
    windows: Optional[int] = 1
    me: int
    te: int
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
    calc_snapshot: Optional[dict] = None
    status: ProductionStatus
    target: Optional[ProductionTarget] = None
    place: Optional[str] = None
    date_planned: Optional[datetime.datetime] = None
    date_released: Optional[datetime.datetime] = None
    code: Optional[str] = None
    contract_code: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime.datetime
    updated_at: Optional[datetime.datetime] = None
    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/blueprint", response_model=BlueprintInfoOut, responses={**ERR_404})
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
            raise HTTPException(404, f"No blueprint or reaction formula found for type_id {product_type_id}")

        bp_type_id = bp.blueprint_type_id
        base_time = eve_repo.base_time(eve_db, bp_type_id, bp.activity_id)
        materials = eve_repo.materials(eve_db, bp_type_id, bp.activity_id)
        # Tag each material with its EVE group (e.g. "Mineral") so the Calculator's
        # custom price-rule dropdown can populate without an extra round-trip.
        mat_groups = eve_repo.type_groups(eve_db, [m["type_id"] for m in materials])
        for m in materials:
            m["group_name"] = (mat_groups.get(m["type_id"]) or {}).get("group_name")
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
            activity_id=bp.activity_id,
            is_reaction=(bp.activity_id == REACTION),
        )
    finally:
        eve_db.close()


def _make_share(db: Session, source: str, body_dump: dict, share_base: Optional[str],
                reuse_code: Optional[str] = None):
    """Store a short share code for this build; return ``(code, reopen_url)``. When
    ``reuse_code`` is a valid existing code (reopening a shared build), keep the SAME code
    instead of minting a new one. Never lets a share failure break the calc."""
    try:
        if reuse_code and reuse_code.isalnum() and len(reuse_code) <= 16:
            code = share_repo.upsert_share(db, reuse_code, source, body_dump)
        else:
            code = share_repo.store_share(db, source, body_dump)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("share code store failed: %s", exc)
        return None, None
    base = (share_base or "").rstrip("/")
    url = f"{base}/manufacturing?job={code}" if base else None
    return code, url


@router.get("/share/{code}")
async def get_share_code(code: str, current_user: UserDB = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Resolve a short share code → ``{source, body}`` to re-run (any logged-in user;
    sharing is cross-user). 404 if unknown or expired."""
    data = share_repo.get_share(db, code)
    if not data:
        raise HTTPException(404, "Share code not found or expired")
    return data


@router.get("/share-image")
async def share_image(data: str, kind: str = "qr"):
    """Render a share code as a QR (default) or Code128 barcode SVG — used by the
    on-screen Share bar. Public (the data is supplied by the client and contains no
    server secret); the response is an image, so it can be used directly in <img src>."""
    from app.services import barcodes
    if not data or len(data) > 4096:
        raise HTTPException(400, "Missing or oversized data")
    try:
        svg = barcodes.code128_svg(data) if kind == "barcode" else barcodes.qr_svg(data)
    except Exception:
        raise HTTPException(400, "Cannot render image")
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.post("/calculate", responses={**ERR_404})
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
            raise HTTPException(404, "Blueprint or reaction formula not found")

        bp_type_id = bp.blueprint_type_id
        qty_per_run = bp.qty_per_run
        is_reaction = bp.activity_id == REACTION
        base_time = eve_repo.base_time(eve_db, bp_type_id, bp.activity_id)
        base_mats = eve_repo.materials(eve_db, bp_type_id, bp.activity_id)

        product_name = eve_repo.type_names(eve_db, [body.product_type_id]).get(
            body.product_type_id, str(body.product_type_id))

    finally:
        eve_db.close()

    # Reactions cannot be researched: ME/TE are always 0 (the formula has no efficiency
    # roll), so ignore any ME/TE the user typed. Rig/structure time bonuses still apply.
    me = 0 if is_reaction else body.me
    te = 0 if is_reaction else body.te

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
        from app.api.facilities_router import accessible_facility_ids
        allowed = accessible_facility_ids(db, current_user.id)
        f = db.query(Facility).filter(Facility.id == body.facility_id).first()
        if f and f.id not in allowed:
            f = None                      # not yours / not shared / not followed-public
        if f:
            if not sci and f.system_cost_index:
                sci = f.system_cost_index
            if not tax and f.tax:
                tax = f.tax
            if f.facility_type in EC_TYPES:
                if not mat_role:
                    mat_role = EC_MATERIAL_ROLE
                if not s_bonus:
                    s_bonus = max(EC_COST_ROLE, f.cost_bonus or 0.0)
            elif not s_bonus and f.cost_bonus:
                s_bonus = f.cost_bonus

    # Character selection: producer's skills recalc job time; seller's skills/standings
    # set the sell-side fees (broker fee + sales tax).
    produce_profile = _industry_profile(db, current_user.id, body.produce_character_id)
    sell_profile = _industry_profile(db, current_user.id, body.sell_character_id)
    skill_time_mult = produce_profile.man_time_mult if produce_profile else 1.0
    broker_fee = sell_profile.broker_fee_pct if sell_profile else body.broker_fee_pct
    sales_tax = sell_profile.sales_tax_pct if sell_profile else 0.0

    inp = CalcInput(
        product_name=product_name,
        product_qty_per_run=qty_per_run,
        runs=body.runs,
        me=me,
        te=te,
        base_time_per_run=base_time,
        materials=[
            Material(type_id=m["type_id"], name=m["name"],
                     base_qty=m["base_qty"], unit_cost=m["unit_cost"])
            for m in materials
        ],
        output_price=body.output_price,
        bpc_cost=body.bpc_cost,
        broker_fee_pct=broker_fee,
        sales_tax_pct=sales_tax,
        skill_time_mult=skill_time_mult,
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
    calc = run_calculation(inp)
    result = asdict(calc)
    result["price_flags"] = {str(t): fl for t, fl in price_flags.items()}
    result["produce_character"] = _profile_out(produce_profile)
    result["sell_character"] = _profile_out(sell_profile)
    result["bp_warning"] = _single_bp_warning(
        db, current_user.id, body.produce_character_id, bp_type_id, product_name)

    # Short shareable code for this build (stored server-side, ~1 week TTL).
    share_code, share_url = _make_share(
        db, "production",
        body.model_dump(exclude={"share_base", "reuse_code", "simulate", "sim", "scenarios"}),
        body.share_base, body.reuse_code)
    result["share_code"] = share_code
    result["share_url"] = share_url

    # IO-22: optional Monte-Carlo profit simulation on this production calc.
    if body.simulate:
        try:
            sim_types = [m.type_id for m in calc.materials] + [body.product_type_id]
            point_buy = {m.type_id: float(m.unit_cost) for m in calc.materials}
            point_sell = {body.product_type_id: body.output_price or None}
            history = sim_data.gather_history(db, current_user.id, sim_types, body.region_id,
                                              point_buy=point_buy, point_sell=point_sell)
            params = (body.sim or SimParamsIn()).to_params()
            run = sim_router.run_calc_simulation(
                db, user_id=current_user.id, project_id=body.project_id, calc=calc,
                product_type_id=body.product_type_id, history=history, params=params,
                product_name=product_name, share_code=share_code, share_url=share_url)
            result["simulation"] = sim_router.run_payload(run)
        except Exception as exc:  # never let the sim break the calc
            logger.warning("production simulation failed: %s", exc)
            result["simulation"] = {"error": str(exc)}

    # IO-23: optional Scenario Simulation analysis on this production calc.
    if body.scenarios is not None:
        try:
            sim_types = [m.type_id for m in calc.materials] + [body.product_type_id]
            point_buy = {m.type_id: float(m.unit_cost) for m in calc.materials}
            point_sell = {body.product_type_id: body.output_price or None}
            history = sim_data.gather_history(db, current_user.id, sim_types, body.region_id,
                                              point_buy=point_buy, point_sell=point_sell)
            params = (body.scenarios.params or body.sim or SimParamsIn()).to_params()
            specs = sim_router.resolve_specs(body.scenarios)
            run = sim_router.run_calc_scenario_analysis(
                db, user_id=current_user.id, project_id=body.project_id, calc=calc,
                product_type_id=body.product_type_id, history=history, params=params,
                product_name=product_name, specs=specs,
                share_code=share_code, share_url=share_url)
            result["scenario_analysis"] = sim_router.scenario_payload(run)
        except Exception as exc:  # never let the analysis break the calc
            logger.warning("production scenario analysis failed: %s", exc)
            result["scenario_analysis"] = {"error": str(exc)}
    return result


class ProductionReportRequest(BaseModel):
    """A finished production calc (the CalcResult the Calculator already rendered) plus
    a small meta block, rendered to a branded PDF. Posting the result keeps the report
    decoupled from a recompute — it formats exactly what the user is looking at."""
    result: dict
    meta: dict = {}
    share_code: Optional[str] = None
    share_url: Optional[str] = None


@router.post("/report/pdf")
async def production_report(body: ProductionReportRequest,
                           current_user: UserDB = Depends(get_current_user)):
    """Detailed production PDF (bill of materials, job-cost breakdown, time, P&L) for a
    single Calculator build — the manufacturing counterpart to the MC / Scenario PDFs."""
    pdf = production_report_pdf.render_production_pdf({
        "meta": body.meta or {},
        "result": body.result or {},
        "share_code": body.share_code or (body.result or {}).get("share_code"),
        "share_url": body.share_url or (body.result or {}).get("share_url"),
    })
    name = (body.meta or {}).get("product_name") or "production"
    safe = "".join(c if c.isalnum() else "_" for c in str(name)).strip("_") or "production"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{safe}_production.pdf"'})


# Recursive make-vs-buy chain + slot assignment

class PriceRule(BaseModel):
    """A custom per-item-group pricing override. ``group`` is an EVE item group name
    (e.g. "Mineral"); items in that group are priced on ``side`` regardless of each
    region's default side. Empty rule list = no overrides (per-region side wins)."""
    group: str
    side: str = "buy"              # 'buy' | 'sell'


class ResolvePricesRequest(BaseModel):
    """Resolve per-type acquire prices across the selected markets — the Calculator's
    material fill uses this to mirror the Chain's multi-region + per-region side +
    custom-rule pricing. Same knobs as ``ChainCalcRequest``'s pricing block."""
    type_ids: List[int]
    region_id: int = 10000002
    region_ids: List[int] = []
    region_sides: dict[int, str] = {}
    include_cj: bool = False
    cj_side: Optional[str] = None
    price_basis: str = "buy"
    price_rules: List[PriceRule] = []
    flag_unrealistic: bool = True
    unrealistic_ratio: float = 0.3
    # Optional haul cost per source (ISK per m³). Folded into each candidate as
    # ``volume × coef`` so the cheapest-source pick accounts for delivery to the home hub.
    region_delivery: dict[int, float] = {}
    cj_delivery: float = 0.0


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
    price_basis: str = "buy"       # default side for any region not in region_sides (and old clients)
    # Per-region Buy/Sell side: ``{region_id: 'buy'|'sell'}``. A region not listed
    # uses ``price_basis``. ``cj_side`` is the side for the optional C-J6MT market.
    region_sides: dict[int, str] = {}
    cj_side: Optional[str] = None
    # Custom group rules: items whose EVE group matches are forced to the rule's side
    # across every region (overrides region_sides). Empty = no overrides.
    price_rules: List[PriceRule] = []
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
    # Nodes the user chose to build even if buying is cheaper (force make): their buy
    # price is dropped so the core must make them. Symmetric to force_buy.
    force_make: List[int] = []
    # Manual blueprint (BPC) cost. ``bpc_cost`` is the TOTAL ISK of the *target's*
    # blueprint for this build (invention/BPC purchase), amortised over the produced
    # quantity; default 0 (already owned / negligible). ``bpc_cost_per_unit`` is an
    # advanced per-node override (product_type_id -> ISK per output unit) for costing
    # intermediate blueprints. Both fold into the make cost and the sim's fixed cost, and
    # WIN over any owned-blueprint estimate.
    bpc_cost: float = 0.0
    bpc_cost_per_unit: dict[int, float] = {}
    # Reactions. True (default) = produce reaction intermediates in-house when cheaper.
    # False = buy reaction components from market instead of running reactions (every
    # reaction-activity node is force-bought; a reaction with no buy price stays makeable).
    include_reactions: bool = True
    # Run reactions "from scratch": force-MAKE every reaction-activity node so no
    # intermediate reaction product is ever bought — the whole reaction sub-tree runs
    # in-house down to raw moon materials. Only meaningful with include_reactions=True
    # (ignored when reactions are bought). Lets the user choose "buy the final product or
    # produce reactions from zero", with no buying of reaction intermediates in between.
    reactions_from_scratch: bool = False
    # Owned blueprints: apply their ME/TE (and a BPC's cost) per node. With
    # use_owned_blueprints the backend auto-picks (BPO else best BPC); blueprint_selection
    # (product_type_id -> OwnedBP key "esi:<id>"/"man:<id>", or a legacy bare manual id)
    # overrides the pick for a node.
    use_owned_blueprints: bool = False
    blueprint_selection: dict[int, str] = {}
    # Manual per-node ME/TE: product_type_id -> [me, te]. Highest priority — wins over
    # an owned blueprint's ME/TE and over the global me_pct/te_pct default. Lets the
    # user tune a single node in the tree without owning a blueprint record for it.
    me_te_overrides: dict[int, List[int]] = {}
    # The user's facilities. When given, each makeable node is built at the cheapest
    # eligible one (the core picks per node, using that facility's rigs).
    structures: List[ChainStructure] = []
    # IO-22: optionally run a Monte-Carlo profit simulation on the resulting plan and
    # store it (per-run PDF + project roll-up). project_id associates the run for the
    # roll-up. ``sim`` carries the simulation knobs (iterations, distributions, risk).
    simulate: bool = False
    project_id: Optional[int] = None
    sim: Optional[SimParamsIn] = None
    # IO-23: optionally run a Scenario Simulation analysis on the resulting plan.
    scenarios: Optional[ScenarioRequestIn] = None
    # Client origin so the server can build the reopen link for the short share code.
    share_base: Optional[str] = None
    # When reopening a shared build, the original code — kept instead of minting a new one.
    reuse_code: Optional[str] = None
    # Character selection (LinkedCharacter.id). The producing character recalcs job
    # time from its Industry / Advanced Industry skills; the selling character sets the
    # simulation's sales tax (Accounting) and broker fee (Broker Relations + standings).
    produce_character_id: Optional[int] = None
    sell_character_id: Optional[int] = None


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


async def _cj_two_sided(type_ids: list[int]) -> dict[int, dict]:
    """Per-type ``{'buy','sell'}`` from the C-J6MT scraper (one slow call per type),
    fanned out across a thread pool. Types with no C-J price are omitted."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = await asyncio.gather(
            *[loop.run_in_executor(ex, market.gnf_local, tid) for tid in type_ids]
        )
    out: dict[int, dict] = {}
    for tid, p in zip(type_ids, results):
        if p:
            out[tid] = {"buy": _fnum(p.get("buy")), "sell": _fnum(p.get("sell"))}
    return out


def _resolve_acquire_prices(
        type_ids: list[int],
        eff_region_ids: list[int],
        region_data: dict[int, dict],
        cj_data: dict[int, dict],
        adj: dict,
        ratio: float,
        *,
        basis: str,
        region_sides: dict[int, str],
        cj_side: Optional[str],
        rules: list,
        group_of: dict[int, Optional[str]],
        overrides: dict[int, float],
        volume_of: Optional[dict[int, float]] = None,
        region_delivery: Optional[dict[int, float]] = None,
        cj_delivery: float = 0.0,
) -> tuple[dict[int, Optional[float]], dict[int, object], dict[int, dict]]:
    """Per-type cheapest *realistic* acquire price across the selected markets, each
    market contributing the Buy/Sell side the user chose (a matching group rule wins
    over the region's side). The opposite side / other regions / ESI adjusted price
    are the scam-price fallback. Shared by the chain calc and the Calculator fill.

    ``region_delivery``/``cj_delivery`` are optional haul costs (ISK per m³) added per
    source: each candidate price gets ``+ volume × coef`` for that market, so the
    cheapest-source choice accounts for delivery (e.g. Jita is only cheaper than the home
    hub once its haul cost is folded in). Default 0 → no delivery (prior behaviour).

    Returns ``(prices, sources, flags)`` keyed by type_id.
    """
    def _opp(side: str) -> str:
        return "sell" if side == "buy" else "buy"

    region_delivery = region_delivery or {}
    volume_of = volume_of or {}

    prices: dict[int, Optional[float]] = {}
    sources: dict[int, object] = {}
    flags: dict[int, dict] = {}
    for tid in type_ids:
        if tid in overrides:
            prices[tid] = overrides[tid]
            sources[tid] = "override"
            continue
        vol = volume_of.get(tid, 0.0)

        def _add(p: Optional[float], coef: float) -> Optional[float]:
            return None if p is None else p + vol * coef

        forced = rule_side(group_of.get(tid), rules)
        primary: list[tuple[Optional[float], object]] = []
        other: list[tuple[Optional[float], object]] = []
        for rid in eff_region_ids:
            side = forced or region_sides.get(rid) or basis
            two = region_data[rid].get(tid, {})
            d = region_delivery.get(rid, 0.0)
            primary.append((_add(two.get(side), d), rid))
            other.append((_add(two.get(_opp(side)), d), rid))
        if tid in cj_data:
            side = forced or cj_side or basis
            two = cj_data[tid]
            primary.append((_add(two.get(side), cj_delivery), "C-J6MT"))
            other.append((_add(two.get(_opp(side)), cj_delivery), "C-J6MT"))
        price, src, flag = resolve_sided(primary, other, adj.get(tid), ratio)
        prices[tid] = price
        if src is not None:
            sources[tid] = src
        if flag:
            flags[tid] = flag
    return prices, sources, flags


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


def _reaction_sci_by_facility(eve_db, facilities) -> dict[int, float]:
    """``{facility_id: reaction cost index}`` resolved from each facility's system via
    ESI (the live ``/industry/systems`` table). Facilities with no system or no ESI
    data are omitted, so the caller falls back to the manufacturing index."""
    named = [f for f in facilities if f and f.system_name]
    if not named:
        return {}
    lowered = list({f.system_name.strip().lower() for f in named})
    rows = eve_db.query(EveSolarSystem.solar_system_id, EveSolarSystem.solar_system_name).filter(
        func.lower(EveSolarSystem.solar_system_name).in_(lowered)).all()
    sysid_by_name = {nm.lower(): sid for sid, nm in rows}
    try:
        table = market.esi_cost_indices()
    except Exception as exc:  # cached ESI table unavailable → fall back to mfg index
        logger.warning("reaction cost-index fetch failed: %s", exc)
        return {}
    out: dict[int, float] = {}
    for f in named:
        sid = sysid_by_name.get(f.system_name.strip().lower())
        idx = (table.get(sid) or {}).get("reaction") if sid else None
        if idx is not None:
            out[f.id] = idx
    return out


def _facility_location(s: ChainStructure, f, rigs, band: str,
                       me_pct: float, te_pct: float,
                       react_sci: Optional[float] = None) -> LocationParams:
    """Turn one of the user's facilities into a chain LocationParams.

    Costs/SCI/tax come from the structure payload; ME/TE/cost *rigs* come from the
    facility's fitted rigs (``rigs``) and are applied per node by the core. The
    global me_pct/te_pct are the manual base the rigs multiply onto. ``react_sci`` is
    the system's reaction cost index (used for reaction nodes); None → mfg index.
    """
    is_ec = bool(f and f.facility_type in EC_TYPES)
    # A facility may run only the activities its *type* allows (EC → manufacturing,
    # refinery → reactions). Eligibility is purely type-based now — job-slot capacity
    # is a single per-character total (see calculate_chain), not a per-facility count,
    # so reactions never land on a Raitaru regardless of any stale per-row slot value.
    allow_man, allow_react = _activity_caps(f.facility_type) if f else (True, True)
    return LocationParams(
        place_id=s.place_id,
        place_name=s.name or (getattr(f, "name", None) if f else None) or f"struct {s.place_id}",
        me_mult=1 - me_pct / 100, te_mult=1 - te_pct / 100,
        sci=s.system_cost_index, react_sci=react_sci,
        tax=s.facility_tax_pct / 100, scc=SCC_SURCHARGE,
        struct_discount=s.structure_discount_pct / 100,
        man_lines=s.man_lines, react_lines=s.react_lines,
        rigs=tuple(rigs), band=band, is_ec=is_ec,
        can_man=allow_man,
        can_react=allow_react,
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
        from app.api.facilities_router import accessible_facility_ids
        allowed = accessible_facility_ids(db, user_id)
        fac_ids = [s.place_id for s in body.structures if s.place_id in allowed]
        facs = {f.id: f for f in db.query(Facility).filter(
            Facility.id.in_(fac_ids or [-1])).all()}
        eve_db = EveSessionLocal()
        try:
            react_sci = _reaction_sci_by_facility(eve_db, list(facs.values()))
            out = []
            for s in body.structures:
                f = facs.get(s.place_id)
                rigs, band, _sec = _facility_rig_context(eve_db, f) if f else ([], "null", None)
                out.append(_facility_location(s, f, rigs, band, body.me_pct, body.te_pct,
                                              react_sci=react_sci.get(s.place_id)))
            return out
        finally:
            eve_db.close()

    # single facility (facility_id) or pure-manual default — one location.
    sci, tax_pct, disc_pct = body.system_cost_index, body.facility_tax_pct, body.structure_discount_pct
    place_id, place_name = body.place_id, body.place_name
    rigs, band, is_ec = [], "null", False
    react_sci: Optional[float] = None
    can_man, can_react = True, True   # pure-manual default builds anything
    if body.facility_id:
        f = db.query(Facility).filter(Facility.id == body.facility_id,
                                      Facility.user_id == user_id).first()
        if f:
            place_id = place_id or f.id
            place_name = place_name or getattr(f, "name", None) or f.facility_type.value
            if not sci and f.system_cost_index:
                sci = f.system_cost_index
            if not tax_pct and f.tax:
                tax_pct = f.tax
            if not disc_pct and f.cost_bonus:
                disc_pct = f.cost_bonus
            is_ec = f.facility_type in EC_TYPES
            can_man, can_react = _activity_caps(f.facility_type)   # a refinery can't manufacture, etc.
            eve_db = EveSessionLocal()
            try:
                rigs, band, _sec = _facility_rig_context(eve_db, f)
                react_sci = _reaction_sci_by_facility(eve_db, [f]).get(f.id)
            finally:
                eve_db.close()
    return [LocationParams(
        place_id=place_id or 1, place_name=place_name or "facility",
        me_mult=1 - body.me_pct / 100, te_mult=1 - body.te_pct / 100,
        sci=sci, react_sci=react_sci, tax=tax_pct / 100, scc=SCC_SURCHARGE,
        struct_discount=disc_pct / 100,
        man_lines=body.man_lines, react_lines=body.react_lines,
        rigs=tuple(rigs), band=band, is_ec=is_ec,
        can_man=can_man, can_react=can_react,
    )]


def _recipe_blueprints(tree: dict) -> dict[int, int]:
    """``{blueprint_type_id: product_type_id}`` over every recipe in the tree —
    lets us key an ESI-owned print (which only carries a blueprint type) to a node."""
    out: dict[int, int] = {}
    for tid, nd in tree.items():
        for rc in nd.get("recipes", []):
            bpt = rc.get("blueprint_type_id")
            if bpt:
                out[bpt] = tid
    return out


def _owned_blueprint_pool(db: Session, user_id: int, tree: dict,
                          bp_names: dict[int, str]) -> dict[int, list]:
    """Merged owned-blueprint pool keyed by product type id: the user's manual
    ``blueprints`` rows ∪ ESI-synced prints across *all* of their linked characters.
    ``bp_names`` (blueprint type_id -> name) is resolved once by the caller.
    Returns ``{product_type_id: [bp_svc.OwnedBP, ...]}``."""
    prod_by_bptype = _recipe_blueprints(tree)
    products = list(tree)
    pool: dict[int, list] = defaultdict(list)

    # manual blueprints (already carry product_type_id, name, cost)
    manual = (db.query(Blueprint)
              .filter(Blueprint.user_id == user_id,
                      Blueprint.product_type_id.in_(products or [-1])).all())
    for bp in manual:
        pool[bp.product_type_id].append(bp_svc.OwnedBP(
            key=f"man:{bp.id}", product_type_id=bp.product_type_id,
            blueprint_type_id=bp.blueprint_type_id, name=bp.name, is_bpo=bp.is_bpo,
            me=bp.me or 0, te=bp.te or 0, runs=None if bp.is_bpo else bp.runs,
            quantity=bp.quantity or 1, cost=bp.cost, source="manual", owner="Manual"))

    # ESI prints across the user's linked characters (per-user pooling)
    chars = db.query(LinkedCharacter).filter(LinkedCharacter.user_id == user_id).all()
    cid_name = {c.character_id: c.character_name for c in chars}
    bptype_ids = list(prod_by_bptype)
    esi_rows = []
    if cid_name and bptype_ids:
        esi_rows = (db.query(EsiBlueprintCopy)
                    .filter(EsiBlueprintCopy.character_id.in_(list(cid_name)),
                            EsiBlueprintCopy.type_id.in_(bptype_ids)).all())
    for r in esi_rows:
        ptid = prod_by_bptype.get(r.type_id)
        if not ptid:
            continue
        bpo = bp_svc.is_bpo(r.runs, r.quantity)
        pool[ptid].append(bp_svc.OwnedBP(
            key=f"esi:{r.item_id}", product_type_id=ptid, blueprint_type_id=r.type_id,
            name=bp_names.get(r.type_id, str(r.type_id)), is_bpo=bpo,
            me=r.material_efficiency or 0, te=r.time_efficiency or 0,
            runs=None if bpo else r.runs, quantity=1, cost=None,
            source="esi", owner=cid_name.get(r.character_id, "?")))
    return pool


def _blueprint_plan(body: ChainCalcRequest, tree: dict, pool: dict[int, list]):
    """Pick an owned print per makeable node from the merged ``pool`` and turn it into
    chain inputs. Explicit ``blueprint_selection`` (product_type_id -> OwnedBP.key, or a
    legacy bare manual id) wins; otherwise ``use_owned_blueprints`` auto-picks the best.
    Returns ``(node_overrides{tid:(me,te)}, bpc_unit{tid:per-unit cost}, chosen{tid:OwnedBP})``."""
    if not body.use_owned_blueprints and not body.blueprint_selection:
        return {}, {}, {}
    by_key = {bp.key: bp for cands in pool.values() for bp in cands}
    selection: dict[int, str] = {}
    for k, v in body.blueprint_selection.items():
        sel = str(v)
        if sel.isdigit():                        # legacy: bare manual Blueprint id
            sel = f"man:{sel}"
        selection[int(k)] = sel

    node_overrides: dict[int, tuple] = {}
    bpc_unit: dict[int, float] = {}
    chosen: dict[int, bp_svc.OwnedBP] = {}
    for tid, nd in tree.items():
        cands = pool.get(tid)
        if not cands:
            continue
        bp = None
        if tid in selection:
            cand = by_key.get(selection[tid])
            if cand and cand.product_type_id == tid:
                bp = cand
        if bp is None and body.use_owned_blueprints:
            bp = bp_svc.pick_best(cands)
        if bp is None:
            continue
        chosen[tid] = bp
        node_overrides[tid] = (bp.me, bp.te)
        if not bp.is_bpo and bp.cost and bp.runs:    # manual BPC cost only (ESI has none)
            qpr = nd["recipes"][0]["qty_per_run"] or 1
            bpc_unit[tid] = bp.cost / (bp.runs * qpr)
    return node_overrides, bpc_unit, chosen


def _bp_report(plan, tree: dict, pool: dict[int, list], node_overrides: dict,
               bp_names: dict[int, str]) -> list[dict]:
    """Full per-made-node blueprint requirements report: required runs + ME/TE, what's
    owned (BPO/BPC across the user's characters), what's missing, and how to acquire it.
    ``bp_names`` (blueprint type_id -> name) is resolved once by the caller."""
    runs_by_type: dict[int, int] = defaultdict(int)
    for j in plan.jobs:
        runs_by_type[j.type_id] += j.runs

    nodes = []
    for tid, dec in plan.decisions.items():
        if dec.decision != "make":
            continue
        recipes = tree.get(tid, {}).get("recipes", [])
        if not recipes:
            continue
        ridx = dec.recipe_index if dec.recipe_index is not None else 0
        rc = recipes[ridx] if 0 <= ridx < len(recipes) else recipes[0]
        bpt = rc.get("blueprint_type_id")
        activity = dec.activity or rc.get("activity") or 1

        best = bp_svc.pick_best(pool.get(tid, []))
        ov = node_overrides.get(tid)
        if ov:
            me, te = ov
        elif best:
            me, te = best.me, best.te
        else:
            me, te = 0, 0
        if activity == REACTION:
            me, te = 0, 0
        nodes.append(bp_svc.MakeNode(
            product_type_id=tid, product_name=tree.get(tid, {}).get("name", str(tid)),
            blueprint_type_id=bpt or 0, blueprint_name=bp_names.get(bpt, str(bpt)),
            activity=activity, runs_needed=runs_by_type.get(tid, 0), me=me, te=te))
    return bp_svc.build_report(nodes, pool)


def _bp_warnings(db: Session, user_id: int, produce_char_id: Optional[int],
                 plan, tree: dict, pool: dict[int, list]) -> list[dict]:
    """Made nodes whose blueprint the *selected producing character* doesn't personally
    own (flags ``owned_elsewhere`` if another of the user's chars / a manual row has it)."""
    if not produce_char_id:
        return []
    char = db.query(LinkedCharacter).filter(
        LinkedCharacter.id == produce_char_id, LinkedCharacter.user_id == user_id).first()
    if not char:
        return []
    made: dict[int, int] = {}        # tid -> blueprint_type_id
    for tid, dec in plan.decisions.items():
        if dec.decision != "make":
            continue
        recipes = tree.get(tid, {}).get("recipes", [])
        if not recipes:
            continue
        ridx = dec.recipe_index if dec.recipe_index is not None else 0
        rc = recipes[ridx] if 0 <= ridx < len(recipes) else recipes[0]
        if rc.get("blueprint_type_id"):
            made[tid] = rc["blueprint_type_id"]
    if not made:
        return []
    owned_types = {
        t for (t,) in db.query(EsiBlueprintCopy.type_id).filter(
            EsiBlueprintCopy.character_id == char.character_id,
            EsiBlueprintCopy.type_id.in_(list(made.values()))).all()
    }
    return [
        {"type_id": tid, "name": tree.get(tid, {}).get("name", str(tid)),
         "owned_elsewhere": bool(pool.get(tid))}
        for tid, bpt in made.items() if bpt not in owned_types
    ]


def _single_bp_warning(db: Session, user_id: int, produce_char_id: Optional[int],
                       bp_type_id: Optional[int], product_name: str) -> Optional[dict]:
    """For the single calculator: the producing char doesn't own the product's blueprint."""
    if not produce_char_id or not bp_type_id:
        return None
    char = db.query(LinkedCharacter).filter(
        LinkedCharacter.id == produce_char_id, LinkedCharacter.user_id == user_id).first()
    if not char:
        return None
    owns = db.query(EsiBlueprintCopy.id).filter(
        EsiBlueprintCopy.character_id == char.character_id,
        EsiBlueprintCopy.type_id == bp_type_id).first()
    if owns:
        return None
    return {"character_name": char.character_name, "product_name": product_name,
            "blueprint_type_id": bp_type_id}


def _industry_profile(db: Session, user_id: int, character_id: Optional[int]):
    """Build an :class:`skills.IndustryProfile` for one of the user's linked characters
    (by LinkedCharacter.id), or None. Skill levels + best NPC standings drive the time
    multipliers (producer) and market fees (seller)."""
    if not character_id:
        return None
    char = db.query(LinkedCharacter).filter(
        LinkedCharacter.id == character_id, LinkedCharacter.user_id == user_id).first()
    if not char:
        return None
    levels = {s.skill_id: (s.trained_level or 0)
              for s in db.query(EsiSkill).filter(EsiSkill.character_id == char.character_id).all()}
    st = db.query(EsiStanding).filter(EsiStanding.character_id == char.character_id).all()
    best_faction = max((s.standing or 0.0 for s in st if s.from_type == "faction"), default=0.0)
    best_corp = max((s.standing or 0.0 for s in st if s.from_type == "npc_corp"), default=0.0)
    return skills_svc.profile_from(char.character_id, char.character_name, levels,
                                   best_faction, best_corp)


def _profile_out(p) -> Optional[dict]:
    if p is None:
        return None
    return {
        "character_id": p.character_id, "character_name": p.character_name,
        "industry_lvl": p.industry_lvl, "advanced_industry_lvl": p.advanced_industry_lvl,
        "accounting_lvl": p.accounting_lvl, "broker_relations_lvl": p.broker_relations_lvl,
        "best_faction_standing": p.best_faction_standing, "best_corp_standing": p.best_corp_standing,
        "man_time_mult": round(p.man_time_mult, 4), "react_time_mult": round(p.react_time_mult, 4),
        "sales_tax_pct": p.sales_tax_pct, "broker_fee_pct": p.broker_fee_pct,
    }


# Cap on how many types one fill can price — the Calculator's material list is short,
# but guard against an oversized request flooding Fuzzwork.
MAX_RESOLVE_TYPES = 500


@router.post("/resolve-prices")
async def resolve_prices(
        body: ResolvePricesRequest,
        current_user: UserDB = Depends(get_current_user),
):
    """Resolve per-type acquire prices across the selected regions, each on the user's
    chosen Buy/Sell side, with custom group rules and the scam-price guard applied —
    the same logic the recursive chain uses. Powers the Calculator's "⚡ Fill"."""
    type_ids = list(dict.fromkeys(int(t) for t in body.type_ids))[:MAX_RESOLVE_TYPES]
    if not type_ids:
        return {"prices": {}, "sources": {}, "flags": {}, "groups": {}}
    eff_region_ids = body.region_ids if body.region_ids else [body.region_id]

    try:
        adj = market.esi_adjusted_prices()
    except Exception:
        adj = {}

    region_data = {rid: _region_two_sided(rid, type_ids) for rid in eff_region_ids}
    cj_data = await _cj_two_sided(type_ids) if body.include_cj else {}

    eve_db = EveSessionLocal()
    try:
        groups = eve_repo.type_groups(eve_db, type_ids)
        _has_delivery = any(body.region_delivery.values()) or body.cj_delivery
        volumes = eve_repo.type_volumes(eve_db, type_ids) if _has_delivery else {}
    finally:
        eve_db.close()
    group_of = {tid: (groups.get(tid) or {}).get("group_name") for tid in type_ids}

    ratio = body.unrealistic_ratio if body.flag_unrealistic else 0.0
    rules = [{"group": r.group, "side": r.side} for r in body.price_rules]
    prices, sources, flags = _resolve_acquire_prices(
        type_ids, eff_region_ids, region_data, cj_data, adj, ratio,
        basis=body.price_basis, region_sides=body.region_sides, cj_side=body.cj_side,
        rules=rules, group_of=group_of, overrides={},
        volume_of=volumes, region_delivery=body.region_delivery, cj_delivery=body.cj_delivery)

    return {
        "prices": {str(t): prices.get(t) for t in type_ids},
        "sources": {str(t): sources.get(t) for t in type_ids},
        "flags": {str(t): flags[t] for t in flags},
        "groups": {str(t): group_of.get(t) for t in type_ids},
    }


class MarketCompareRequest(BaseModel):
    """Per-region two-sided prices for a set of types — powers the Calculator's
    "Analyze market" comparison across exactly the markets the user selected for the
    material fill (instead of a hardcoded Jita-vs-C-J view)."""
    type_ids: List[int]
    region_ids: List[int] = []
    include_cj: bool = False


@router.post("/market-compare")
async def market_compare(
        body: MarketCompareRequest,
        current_user: UserDB = Depends(get_current_user),
):
    """Both Buy/Sell sides for each selected region (and optionally C-J6MT) plus each
    type's packaged volume — the frontend builds the side-by-side comparison and folds in
    per-market delivery (ISK/m³) itself, so Analyze and the ⚡ fill use the same markets."""
    type_ids = list(dict.fromkeys(int(t) for t in body.type_ids))[:MAX_RESOLVE_TYPES]
    if not type_ids:
        return {"regions": {}, "cj": {}, "volumes": {}}
    region_ids = body.region_ids or [10000002]

    region_data = {rid: _region_two_sided(rid, type_ids) for rid in region_ids}
    cj_data = await _cj_two_sided(type_ids) if body.include_cj else {}

    eve_db = EveSessionLocal()
    try:
        volumes = eve_repo.type_volumes(eve_db, type_ids)
    finally:
        eve_db.close()

    return {
        "regions": {str(rid): {str(t): region_data[rid].get(t, {"buy": None, "sell": None})
                               for t in type_ids}
                    for rid in region_ids},
        "cj": {str(t): cj_data[t] for t in cj_data},
        "volumes": {str(t): volumes.get(t, 0.0) for t in type_ids},
    }


@router.post("/calculate-chain", responses={**ERR_400, **ERR_404})
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
        bp_type_ids = {rc["blueprint_type_id"] for nd in tree.values()
                       for rc in nd.get("recipes", []) if rc.get("blueprint_type_id")}
        bp_names = eve_repo.type_names(eve_db, list(bp_type_ids))
    finally:
        eve_db.close()
    if not tree or body.product_type_id not in tree:
        raise HTTPException(404, f"No build tree for type_id {body.product_type_id}")
    if not tree[body.product_type_id]["recipes"]:
        raise HTTPException(400, "Target product has no manufacturing/reaction recipe")
    if body.qty < 1 or body.qty > MAX_CHAIN_QTY:
        raise HTTPException(400, f"qty must be between 1 and {MAX_CHAIN_QTY:,}")

    type_ids = list(tree)
    eff_region_ids = body.region_ids if body.region_ids else [body.region_id]

    try:
        adj = market.esi_adjusted_prices()
    except Exception:
        adj = {}

    # Both market sides from every selected region (one fetch each), plus optional C-J.
    region_data = {rid: _region_two_sided(rid, type_ids) for rid in eff_region_ids}
    cj_data = await _cj_two_sided(type_ids) if body.include_cj else {}

    overrides = {int(k): float(v) for k, v in body.price_overrides.items()}
    ratio = body.unrealistic_ratio if body.flag_unrealistic else 0.0

    # Per type: cheapest *realistic* price across the selected markets, each on the
    # user's chosen Buy/Sell side (a group rule overrides the region default); another
    # region or the other side beats a scam order before falling back to ESI adjusted.
    group_name_of = {tid: tree.get(tid, {}).get("group_name") for tid in type_ids}
    rules = [{"group": r.group, "side": r.side} for r in body.price_rules]
    buy_prices, price_source, price_flags = _resolve_acquire_prices(
        type_ids, eff_region_ids, region_data, cj_data, adj, ratio,
        basis=body.price_basis, region_sides=body.region_sides, cj_side=body.cj_side,
        rules=rules, group_of=group_name_of, overrides=overrides)

    facilities = _build_facilities(body, db, current_user.id)
    # Character selection: producer drives job-time skills; seller drives sim fees.
    produce_profile = _industry_profile(db, current_user.id, body.produce_character_id)
    sell_profile = _industry_profile(db, current_user.id, body.sell_character_id)
    tm_man = produce_profile.man_time_mult if produce_profile else 1.0
    tm_react = produce_profile.react_time_mult if produce_profile else 1.0
    # Owned blueprints: merged pool (manual ∪ my ESI prints) → per-node ME/TE + BPC cost.
    owned_pool = _owned_blueprint_pool(db, current_user.id, tree, bp_names)
    node_overrides, bpc_unit, chosen_bps = _blueprint_plan(body, tree, owned_pool)
    # Manual per-node ME/TE wins over the owned-blueprint pick (and the global default).
    for tid, me_te in body.me_te_overrides.items():
        if isinstance(me_te, (list, tuple)) and len(me_te) == 2:
            node_overrides[int(tid)] = (int(me_te[0]), int(me_te[1]))
    # Manual blueprint (BPC) cost — wins over the owned-blueprint estimate. The target's
    # total is amortised over the produced quantity; per-unit entries apply directly.
    if body.bpc_cost and body.qty > 0:
        bpc_unit[body.product_type_id] = body.bpc_cost / body.qty
    for tid, per_unit in body.bpc_cost_per_unit.items():
        bpc_unit[int(tid)] = float(per_unit)
    req = from_bom(body.product_type_id, body.qty, tree, buy_prices, adj, facilities,
                   bpc_unit=bpc_unit, node_overrides=node_overrides,
                   time_mult_man=tm_man, time_mult_react=tm_react)

    # Skip-making (force buy): drop those nodes' recipes so the core can only buy
    # them. Guard nodes that have nothing to buy — leave them makeable.
    forced_skipped: list[int] = []
    force_buy_ids = set(body.force_buy)
    # Reactions off → buy every reaction-activity node instead of producing it (except the
    # target itself: "no reactions" can't mean "don't build the thing you asked for").
    reaction_node_ids: set[int] = set()
    if not body.include_reactions:
        reaction_node_ids = {
            tid for tid, nd in tree.items()
            if tid != body.product_type_id and nd.get("recipes")
            and all(rc["activity"] == REACTION for rc in nd["recipes"])
        }
        force_buy_ids |= reaction_node_ids
    for tid in force_buy_ids:
        n = req.nodes.get(tid)
        if not n or not n.recipes:
            continue
        if n.buy_price is None:
            forced_skipped.append(tid)
            continue
        req.nodes[tid] = replace(n, recipes=())

    # Reactions from scratch: force-MAKE every reaction-activity node so no intermediate
    # reaction product is bought — the whole reaction sub-tree runs in-house. Only when
    # reactions are in-house (include_reactions); otherwise they're bought above.
    scratch_make_ids: set[int] = set()
    if body.include_reactions and body.reactions_from_scratch:
        scratch_make_ids = {
            tid for tid, nd in tree.items()
            if tid != body.product_type_id and nd.get("recipes")
            and all(rc["activity"] == REACTION for rc in nd["recipes"])
        }

    # Force-make: drop the buy option so the core must build it. force_buy wins on conflict.
    forced_make_skipped: list[int] = []
    for tid in (set(body.force_make) | scratch_make_ids) - force_buy_ids:
        n = req.nodes.get(tid)
        if not n:
            continue
        if not n.recipes:
            forced_make_skipped.append(tid)        # nothing to make → can't force
            continue
        req.nodes[tid] = replace(n, buy_price=None)

    plan, engine = chain_engine.solve(req)   # native Haskell core, falls back to Python

    # Guard against runaway plans: a deep capital chain at high qty emits an enormous
    # number of job-chunks, which blows up the response JSON, the inline simulation and
    # the browser (the "everything froze" at qty=1000). Fail fast with a clear message
    # instead of melting the server.
    if len(plan.jobs) > MAX_CHAIN_JOBS:
        raise HTTPException(
            400, f"Plan too large: {len(plan.jobs):,} production jobs. Reduce the quantity "
                 f"(deep reaction/capital chains grow very fast with qty).")

    # Capacity schedule: lay the jobs into dependency-ordered stages within the
    # character's job slots. Slots are a single per-character total (man_lines /
    # react_lines), not a per-facility count — in EVE the manufacturing/reaction job
    # cap comes from the pilot's skills, shared across every structure they use.
    schedule = stage_schedule(plan.jobs, body.man_lines, body.react_lines)

    # Blueprint requirements report (all made nodes) + missing-print warnings for the
    # selected producing character.
    bp_report = _bp_report(plan, tree, owned_pool, node_overrides, bp_names)
    bp_warnings = _bp_warnings(db, current_user.id, body.produce_character_id,
                               plan, tree, owned_pool)

    response = {
        "plan": _plan_dict(plan),
        "assignment": _chain_assignment(plan, facilities),
        "schedule": schedule,
        "final_cost": round(float(plan.total_cost), 2),
        "engine": engine,
        "multi_location": len(facilities) > 1,
        "price_basis": body.price_basis,
        # Distinct EVE item groups among the buyable materials — feeds the custom
        # group-rule dropdown so the user can target e.g. "Mineral".
        "material_groups": sorted({
            g for tid, g in group_name_of.items()
            if g and tid != body.product_type_id
        }),
        "price_source": {str(t): src for t, src in price_source.items()},
        "price_flags": {str(t): fl for t, fl in price_flags.items()},
        "force_buy_skipped": forced_skipped,
        "force_make_skipped": forced_make_skipped,
        "include_reactions": body.include_reactions,
        "reactions_from_scratch": body.reactions_from_scratch,
        # reaction nodes actually bought (force-buy succeeded), vs. left makeable (no buy price)
        "reactions_bought": sorted(reaction_node_ids - set(forced_skipped)),
        # reaction nodes forced to be made in-house by the from-scratch mode
        "reactions_made_from_scratch": sorted(scratch_make_ids - force_buy_ids),
        "bpc_cost_applied": {str(t): float(c) for t, c in bpc_unit.items() if c},
        "bp_report": bp_report,
        "bp_summary": bp_svc.summarize(bp_report),
        "bp_warnings": bp_warnings,
        "blueprint_selection": {str(t): bp.key for t, bp in chosen_bps.items()},
        "produce_character": _profile_out(produce_profile),
        "sell_character": _profile_out(sell_profile),
    }

    # Short shareable code for this chain build (stored server-side, ~1 week TTL).
    share_code, share_url = _make_share(
        db, "chain",
        body.model_dump(exclude={"share_base", "reuse_code", "simulate", "sim", "scenarios"}),
        body.share_base, body.reuse_code)
    response["share_code"] = share_code
    response["share_url"] = share_url

    # IO-22: optional Monte-Carlo profit simulation on the resulting plan.
    if body.simulate:
        try:
            primary = eff_region_ids[0]
            sim_types = [s.type_id for s in plan.shopping_list] + [body.product_type_id]
            group_of = {tid: nd.get("category_id") for tid, nd in tree.items()}
            point_sell = {tid: (region_data.get(primary, {}).get(tid, {}) or {}).get("sell")
                          for tid in sim_types}
            history = sim_data.gather_history(
                db, current_user.id, sim_types, primary,
                group_of=group_of, point_buy=buy_prices, point_sell=point_sell)
            simin = body.sim or SimParamsIn()
            params = simin.to_params()
            if (body.sim is None or body.sim.slots <= 1) and (body.man_lines + body.react_lines) > 0:
                params.slots = max(1, body.man_lines + body.react_lines)
            # The selling character's skills/standings set the sell-side fees.
            broker = sell_profile.broker_fee_pct if sell_profile else simin.broker_fee_pct
            sales = sell_profile.sales_tax_pct if sell_profile else simin.sales_tax_pct
            run = sim_router.run_chain_simulation(
                db, user_id=current_user.id, project_id=body.project_id, plan=plan,
                production_time_s=int(schedule.get("total_time_s") or 0), history=history,
                params=params, product_name=tree[body.product_type_id]["name"],
                broker_fee_pct=broker, sales_tax_pct=sales,
                share_code=share_code, share_url=share_url)
            response["simulation"] = sim_router.run_payload(run)
        except Exception as exc:  # never let the sim break the chain calc
            logger.warning("chain simulation failed: %s", exc)
            response["simulation"] = {"error": str(exc)}

    # IO-23: optional Scenario Simulation analysis on the resulting plan.
    if body.scenarios is not None:
        try:
            primary = eff_region_ids[0]
            sim_types = [s.type_id for s in plan.shopping_list] + [body.product_type_id]
            group_of = {tid: nd.get("category_id") for tid, nd in tree.items()}
            point_sell = {tid: (region_data.get(primary, {}).get(tid, {}) or {}).get("sell")
                          for tid in sim_types}
            history = sim_data.gather_history(
                db, current_user.id, sim_types, primary,
                group_of=group_of, point_buy=buy_prices, point_sell=point_sell)
            simin = body.scenarios.params or body.sim or SimParamsIn()
            params = simin.to_params()
            if simin.slots <= 1 and (body.man_lines + body.react_lines) > 0:
                params.slots = max(1, body.man_lines + body.react_lines)
            broker = sell_profile.broker_fee_pct if sell_profile else simin.broker_fee_pct
            sales = sell_profile.sales_tax_pct if sell_profile else simin.sales_tax_pct
            specs = sim_router.resolve_specs(body.scenarios)
            run = sim_router.run_chain_scenario_analysis(
                db, user_id=current_user.id, project_id=body.project_id, plan=plan,
                production_time_s=int(schedule.get("total_time_s") or 0), history=history,
                params=params, product_name=tree[body.product_type_id]["name"],
                broker_fee_pct=broker, sales_tax_pct=sales, specs=specs,
                share_code=share_code, share_url=share_url)
            response["scenario_analysis"] = sim_router.scenario_payload(run)
        except Exception as exc:  # never let the analysis break the chain calc
            logger.warning("chain scenario analysis failed: %s", exc)
            response["scenario_analysis"] = {"error": str(exc)}

    return _to_jsonable(response)


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


@router.get("/facility-bonuses", responses={**ERR_404})
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
    from app.api.facilities_router import accessible_facility_ids
    f = db.query(Facility).filter(Facility.id == facility_id).first()
    if not f or f.id not in accessible_facility_ids(db, current_user.id):
        raise HTTPException(404, "Facility not found")

    eve_db = EveSessionLocal()
    try:
        rigs, band, sec = _facility_rig_context(eve_db, f)

        prod = eve_db.query(EveType).filter(EveType.type_id == product_type_id).first()
        grp = eve_db.query(EveGroup).filter(EveGroup.group_id == prod.group_id).first() if prod else None
        cat_id = grp.category_id if grp else None
        group_name = grp.group_name if grp else None
        meta_group_id = eve_repo.meta_group_for(eve_db, product_type_id)

        eff = effective_bonuses(rigs, band, cat_id, group_name, meta_group_id=meta_group_id)

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
        kind: Optional[str] = None,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    q = db.query(ProductionJob).filter(ProductionJob.user_id == current_user.id)
    if project_id:  q = q.filter(ProductionJob.project_id == project_id)
    if job_status:  q = q.filter(ProductionJob.status == job_status)
    if kind:        q = q.filter(ProductionJob.kind == kind)
    return q.order_by(ProductionJob.date_planned.desc()).all()


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
        body: JobCreate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    j = ProductionJob(user_id=current_user.id, **body.model_dump())
    db.add(j)
    db.flush()  # assign j.id
    db.add(ProductionStatusEvent(
        job_id=j.id, from_status=None, status=_status_val(j.status),
        note="created", at=utcnow()))
    db.commit()
    db.refresh(j)
    return j


@router.get("/jobs/{job_id}", response_model=JobOut, responses={**ERR_404})
async def get_job(
        job_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    return _job_or_404(db, job_id, current_user.id)


@router.get("/jobs/{job_id}/history", responses={**ERR_404})
async def job_history(
        job_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Status timeline for one PAK job — each transition with its timestamp, plus the
    planned/released times and total elapsed (what changed when, and how long it took)."""
    j = _job_or_404(db, job_id, current_user.id)
    events = (db.query(ProductionStatusEvent)
              .filter(ProductionStatusEvent.job_id == j.id)
              .order_by(ProductionStatusEvent.at).all())
    elapsed = ((j.date_released - j.date_planned).total_seconds()
               if j.date_released and j.date_planned else None)
    return {
        "job_id": j.id,
        "product": j.product_name,
        "place": j.place,
        "status": _status_val(j.status),
        "date_planned": j.date_planned.isoformat() if j.date_planned else None,
        "date_released": j.date_released.isoformat() if j.date_released else None,
        "elapsed_seconds": elapsed,
        "events": [
            {"from_status": e.from_status, "status": e.status,
             "at": e.at.isoformat() if e.at else None, "note": e.note}
            for e in events
        ],
    }


@router.patch("/jobs/{job_id}", response_model=JobOut, responses={**ERR_404})
async def update_job(
        job_id: int,
        body: JobUpdate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    j = _job_or_404(db, job_id, current_user.id)
    changes = body.model_dump(exclude_none=True)
    new_status = changes.get("status")
    entered_progress = (new_status is not None
                        and _status_val(new_status) != _status_val(j.status)
                        and _status_val(new_status) == _status_val(ProductionStatus.IN_PROGRESS))
    if new_status is not None and _status_val(new_status) != _status_val(j.status):
        _log_job_status(db, j, new_status, note="manual status change")
    for field, val in changes.items():
        setattr(j, field, val)
    # Entering In Progress auto-stamps the release date (unless the caller set one).
    if entered_progress and "date_released" not in changes:
        _mark_released(j)
    j.updated_at = utcnow()
    db.commit()
    db.refresh(j)
    return j


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT, responses={**ERR_404})
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


@router.post("/jobs/{job_id}/issue", responses={**ERR_400, **ERR_404})
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
        _log_job_status(db, job, ProductionStatus.IN_PROGRESS, note="materials issued")
        job.status = ProductionStatus.IN_PROGRESS
        _mark_released(job)
    job.updated_at = utcnow()
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


@router.post("/jobs/{job_id}/receive", responses={**ERR_400, **ERR_404})
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

    _log_job_status(db, job, ProductionStatus.COMPLETED, note="output received")
    job.status = ProductionStatus.COMPLETED
    _mark_released(job)  # set-if-empty: keep the In-Progress stamp if it has one
    job.updated_at = utcnow()
    db.commit()
    db.refresh(item)

    return {"job_id": job.id, "received_qty": qty, "unit_cost": unit, "inventory_id": item.id}


@router.get("/jobs/{job_id}/movements", responses={**ERR_404})
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


def _status_val(s) -> Optional[str]:
    """Normalise a ProductionStatus enum (or raw string) to its string value."""
    if s is None:
        return None
    return s.value if hasattr(s, "value") else str(s)


def _log_job_status(db: Session, job: ProductionJob, new_status, note: Optional[str] = None) -> None:
    """Append a PAK status-history row (append-only timeline). Call *before* setting
    ``job.status`` so ``from_status`` captures the previous value."""
    db.add(ProductionStatusEvent(
        job_id=job.id, from_status=_status_val(job.status),
        status=_status_val(new_status), note=note,
        at=utcnow()))


def _mark_released(job: ProductionJob) -> None:
    """Stamp the release date the first time a PAK becomes active (In Progress).
    Set-if-empty, so a later transition (e.g. Completed) keeps the original timestamp
    and a caller-supplied ``date_released`` is never overwritten."""
    if not job.date_released:
        job.date_released = utcnow()


def _job_or_404(db: Session, job_id: int, user_id: int) -> ProductionJob:
    j = db.query(ProductionJob).filter(
        ProductionJob.id == job_id,
        ProductionJob.user_id == user_id,
    ).first()
    if not j:
        raise HTTPException(404, "Production job not found")
    return j
