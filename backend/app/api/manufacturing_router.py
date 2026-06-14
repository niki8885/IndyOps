"""
Manufacturing calculator + Production Job (PAK) CRUD.

Activity IDs: 1=Manufacturing, 3=ResearchTE, 4=ResearchME, 5=Copying, 8=Invention
"""
import datetime
from dataclasses import asdict
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
from app.repositories import eve as eve_repo
from app.services.costing import plan_fifo
from app.services.manufacturing import CalcInput, Material, run_calculation

router = APIRouter()

# Engineering Complex (Raitaru/Azbel/Sotiyo) manufacturing role bonuses
EC_MATERIAL_ROLE = 1.0   # −1% material
EC_COST_ROLE     = 3.0   # −3% job cost
EC_TYPES = (FacilityType.RAITARU, FacilityType.AZBEL, FacilityType.SOTIYO)


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

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
    product_type_id:      int
    facility_id:          Optional[int]   = None
    runs:                 int   = 1
    windows:              int   = 1    # parallel production slots
    me:                   int   = 0
    te:                   int   = 0
    bpc_cost:             float = 0.0
    output_price:         float = 0.0
    broker_fee_pct:       float = 3.6
    system_cost_index:    float = 0.0    # fraction
    facility_tax_pct:     float = 0.0
    structure_bonus_pct:  float = 0.0
    material_bonus_pct:   float = 0.0    # rig ME (security-scaled)
    time_bonus_pct:       float = 0.0    # rig TE
    material_role_pct:    float = 0.0    # structure role ME (auto from EC if 0)
    time_role_pct:        float = 0.0    # structure role TE
    estimated_item_value: Optional[float] = None
    material_prices:      List[MaterialPrice] = []


class JobCreate(BaseModel):
    product_type_id:   int
    product_name:      str
    blueprint_type_id: Optional[int]   = None
    blueprint_name:    Optional[str]   = None
    facility_id:       Optional[int]   = None
    project_id:        Optional[int]   = None
    runs:              int   = 1
    windows:           int   = 1
    me:                int   = 0
    te:                int   = 0
    bpc_cost:          float = 0.0
    paks:              Optional[int]   = None
    units_per_pak:     Optional[int]   = None
    pack_tier:         Optional[str]   = None
    pak_reward:        Optional[float] = None
    sell_price:        Optional[float] = None
    jita_sell:         Optional[float] = None
    jita_buy:          Optional[float] = None
    cj_sell:           Optional[float] = None
    cj_buy:            Optional[float] = None
    initial_contract_price: Optional[float] = None
    return_contract_price:  Optional[float] = None
    status:   ProductionStatus = ProductionStatus.PLANNING
    target:   Optional[ProductionTarget] = None
    place:    Optional[str]   = None
    date_planned:  Optional[datetime.datetime] = None
    date_released: Optional[datetime.datetime] = None
    code:          Optional[str] = None
    contract_code: Optional[str] = None
    note:          Optional[str] = None
    calc_snapshot: Optional[dict] = None


class JobUpdate(BaseModel):
    facility_id:    Optional[int]   = None
    project_id:     Optional[int]   = None
    runs:           Optional[int]   = None
    windows:        Optional[int]   = None
    me:             Optional[int]   = None
    te:             Optional[int]   = None
    bpc_cost:       Optional[float] = None
    paks:           Optional[int]   = None
    units_per_pak:  Optional[int]   = None
    pack_tier:      Optional[str]   = None
    pak_reward:     Optional[float] = None
    sell_price:     Optional[float] = None
    jita_sell:      Optional[float] = None
    jita_buy:       Optional[float] = None
    cj_sell:        Optional[float] = None
    cj_buy:         Optional[float] = None
    initial_contract_price: Optional[float] = None
    return_contract_price:  Optional[float] = None
    status:   Optional[ProductionStatus] = None
    target:   Optional[ProductionTarget] = None
    place:    Optional[str]   = None
    date_planned:  Optional[datetime.datetime] = None
    date_released: Optional[datetime.datetime] = None
    code:          Optional[str] = None
    contract_code: Optional[str] = None
    note:          Optional[str] = None
    calc_snapshot: Optional[dict] = None


class JobOut(BaseModel):
    id:               int
    user_id:          int
    project_id:       Optional[int]
    facility_id:      Optional[int]
    blueprint_type_id: Optional[int]
    blueprint_name:   Optional[str]
    product_type_id:  int
    product_name:     str
    runs:             int
    windows:          Optional[int] = 1
    me:               int
    te:               int
    bpc_cost:         Optional[float]
    paks:             Optional[int]
    units_per_pak:    Optional[int]
    pack_tier:        Optional[str]
    pak_reward:       Optional[float]
    sell_price:       Optional[float]
    jita_sell:        Optional[float]
    jita_buy:         Optional[float]
    cj_sell:          Optional[float]
    cj_buy:           Optional[float]
    initial_contract_price: Optional[float]
    return_contract_price:  Optional[float]
    calc_snapshot:    Optional[dict]
    status:           ProductionStatus
    target:           Optional[ProductionTarget]
    place:            Optional[str]
    date_planned:     Optional[datetime.datetime]
    date_released:    Optional[datetime.datetime]
    code:             Optional[str]
    contract_code:    Optional[str]
    note:             Optional[str]
    created_at:       datetime.datetime
    updated_at:       Optional[datetime.datetime]

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

        bp_type_id   = bp.blueprint_type_id
        base_time    = eve_repo.base_time(eve_db, bp_type_id)
        materials    = eve_repo.materials(eve_db, bp_type_id)
        names        = eve_repo.type_names(eve_db, [bp_type_id, product_type_id])

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

        bp_type_id  = bp.blueprint_type_id
        qty_per_run = bp.qty_per_run
        base_time   = eve_repo.base_time(eve_db, bp_type_id)
        base_mats   = eve_repo.materials(eve_db, bp_type_id)

        product_name = eve_repo.type_names(eve_db, [body.product_type_id]).get(
            body.product_type_id, str(body.product_type_id))

    finally:
        eve_db.close()

    # merge user prices into base materials
    price_map = {p.type_id: p.unit_cost for p in body.material_prices}
    materials = [
        {**m, "unit_cost": price_map.get(m["type_id"], 0.0)}
        for m in base_mats
    ]

    # Estimated Item Value (EVE-accurate): Σ base_qty × ESI adjusted price
    eiv = body.estimated_item_value
    if not eiv or eiv <= 0:
        try:
            adj = market.esi_adjusted_prices()
            computed = sum((m["base_qty"] * body.runs) * adj.get(m["type_id"], 0.0) for m in base_mats)
            eiv = computed if computed > 0 else None
        except Exception:
            eiv = None   # run_calculation will fall back to material cost

    # pull facility defaults if provided
    sci     = body.system_cost_index
    tax     = body.facility_tax_pct
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
            # Engineering Complex role bonuses (auto unless caller set them)
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
    return asdict(run_calculation(inp))


# ─── Facility rig bonuses (dogma-based) ──────────────────────────────────────

# EVE category IDs. Affected sets are taken from the rig multiplier attribute
# descriptions in dgmAttributeTypes (e.g. attr 2561 "Structure" explicitly lists
# Structure Components/Modules, Upwell & Starbase Structures, *Fuel Blocks*).
_CAT_SHIP, _CAT_MODULE, _CAT_CHARGE, _CAT_DRONE = 6, 7, 8, 18
_CAT_IMPLANT, _CAT_FIGHTER, _CAT_POS_STRUCT = 20, 87, 23
_CAT_UPWELL, _CAT_STRUCT_MODULE = 65, 66


def _ship_size(group_name: str) -> Optional[str]:
    g = (group_name or "").lower()
    if any(k in g for k in ("frigate", "destroyer", "shuttle", "corvette", "capsule")):
        return "small"
    if any(k in g for k in ("cruiser", "battlecruiser")):
        return "medium"
    if any(k in g for k in ("battleship", "freighter", "dreadnought", "carrier",
                            "capital", "titan", "supercarrier", "industrial ship")):
        return "large"
    return None


def _rig_applies(rig_name: str, cat_id: Optional[int], group_name: str) -> bool:
    """
    Match an engineering rig to a product, based on the official affected-category
    lists from the SDE rig multiplier attribute descriptions.
    """
    n = (rig_name or "").lower()
    gn = (group_name or "").lower()
    if "equipment" in n:
        # Ship Modules, Ship Rigs, Personal Deployables, Implants, Cargo Containers
        return cat_id in (_CAT_MODULE, _CAT_IMPLANT) or "cargo container" in gn or "deployable" in gn
    if "ammunition" in n:
        return cat_id == _CAT_CHARGE
    if "drone" in n or "fighter" in n:
        return cat_id in (_CAT_DRONE, _CAT_FIGHTER)
    if "capital component" in n:
        return "component" in gn
    if "component" in n:            # Advanced/T2/T3 Components, Tools, Data Interfaces
        return "component" in gn or "tool" in gn or "data interface" in gn
    if "structure" in n:
        # Structure Components/Modules, Upwell & Starbase Structures, Fuel Blocks
        return (cat_id in (_CAT_UPWELL, _CAT_STRUCT_MODULE, _CAT_POS_STRUCT)
                or "fuel block" in gn or "structure" in gn or "component" in gn)
    if "ship" in n:
        if cat_id != _CAT_SHIP:
            return False
        size = _ship_size(group_name)
        if "small" in n:  return size == "small"
        if "medium" in n: return size == "medium"
        if "large" in n:  return size == "large"
        return True
    return False


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

    rig_ids = [r for r in (f.rig1_type_id, f.rig2_type_id, f.rig3_type_id) if r]

    eve_db = EveSessionLocal()
    try:
        sec = None
        if f.system_name:
            sysrow = eve_db.query(EveSolarSystem).filter(
                EveSolarSystem.solar_system_name.ilike(f.system_name.strip())
            ).first()
            sec = sysrow.security if sysrow else None
        band = "hi" if (sec is not None and sec >= 0.45) else "low" if (sec is not None and sec > 0.0) else "null"

        prod = eve_db.query(EveType).filter(EveType.type_id == product_type_id).first()
        grp = eve_db.query(EveGroup).filter(EveGroup.group_id == prod.group_id).first() if prod else None
        cat_id = grp.category_id if grp else None
        group_name = grp.group_name if grp else None

        # batch the per-rig SDE lookups (was a query per rig — N+1)
        rig_types = {t.type_id: t for t in
                     eve_db.query(EveType).filter(EveType.type_id.in_(rig_ids or [-1])).all()}
        rig_bonuses = {rb.type_id: rb for rb in
                       eve_db.query(EveRigBonus).filter(EveRigBonus.type_id.in_(rig_ids or [-1])).all()}

        rigs_out, tot_me, tot_te, tot_cost = [], 0.0, 0.0, 0.0
        for rid in rig_ids:
            t = rig_types.get(rid)
            rb = rig_bonuses.get(rid)
            name = t.type_name if t else str(rid)
            if not rb:
                rigs_out.append({"type_id": rid, "name": name, "applies": False, "reason": "no industry bonus"})
                continue
            mod = {"hi": rb.hisec_mod, "low": rb.lowsec_mod, "null": rb.nullsec_mod}[band] or 1.0
            applies = _rig_applies(name, cat_id, group_name)
            eff_me, eff_te, eff_cost = abs(rb.me_bonus or 0) * mod, abs(rb.te_bonus or 0) * mod, abs(rb.cost_bonus or 0) * mod
            if applies:
                tot_me += eff_me; tot_te += eff_te; tot_cost += eff_cost
            rigs_out.append({
                "type_id": rid, "name": name, "applies": applies,
                "me_pct": round(eff_me, 2), "te_pct": round(eff_te, 2), "cost_pct": round(eff_cost, 2),
            })

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
            "total_me_pct": round(tot_me, 2),
            "total_te_pct": round(tot_te, 2),
            "total_cost_pct": round(tot_cost, 2),
            "structure_role": structure_role,
            "rigs": rigs_out,
        }
    finally:
        eve_db.close()


# ─── Production Job CRUD ────────────────────────────────────────────────────

@router.get("/jobs", response_model=List[JobOut])
async def list_jobs(
    project_id:  Optional[int]             = None,
    job_status:  Optional[ProductionStatus] = None,
    current_user: UserDB  = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    q = db.query(ProductionJob).filter(ProductionJob.user_id == current_user.id)
    if project_id:  q = q.filter(ProductionJob.project_id == project_id)
    if job_status:  q = q.filter(ProductionJob.status == job_status)
    return q.order_by(ProductionJob.date_planned.desc()).all()


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    body:         JobCreate,
    current_user: UserDB  = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    j = ProductionJob(user_id=current_user.id, **body.model_dump())
    db.add(j)
    db.commit()
    db.refresh(j)
    return j


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(
    job_id: int,
    current_user: UserDB  = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    return _job_or_404(db, job_id, current_user.id)


@router.patch("/jobs/{job_id}", response_model=JobOut)
async def update_job(
    job_id: int,
    body:   JobUpdate,
    current_user: UserDB  = Depends(get_current_user),
    db:           Session = Depends(get_db),
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
    current_user: UserDB  = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    j = _job_or_404(db, job_id, current_user.id)
    db.delete(j)
    db.commit()


# ─── Inventory LIFO/FIFO analysis ───────────────────────────────────────────

@router.get("/inventory-analysis")
async def inventory_analysis(
    method:     str = "FIFO",   # FIFO | LIFO
    project_id: Optional[int] = None,
    organisation_id: Optional[int] = None,
    current_user: UserDB  = Depends(get_current_user),
    db:           Session = Depends(get_db),
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
        total_qty   = sum(i.quantity for i in items)
        priced      = [i for i in items if i.price]
        total_value = sum(i.quantity * (i.price or 0) for i in items)
        avg_cost    = total_value / total_qty if total_qty else 0

        result.append({
            "key":          key,
            "eve_type_id":  items[0].eve_type_id,
            "name":         items[0].name,
            "method":       method.upper(),
            "total_qty":    total_qty,
            "lots":         len(items),
            "priced_lots":  len(priced),
            "avg_cost_isk": round(avg_cost, 2),
            "total_value_isk": round(total_value, 2),
            "lots_detail": [
                {
                    "id":        i.id,
                    "qty":       i.quantity,
                    "price":     i.price,
                    "place":     i.place,
                    "created_at": i.created_at.isoformat() if i.created_at else None,
                }
                for i in items
            ],
        })

    return {"method": method.upper(), "items": result}


# ─── Warehouse availability + material write-off ────────────────────────────

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
        total_val  = sum(l.quantity * l.price for l in lots if l.price)
        wavg = round(total_val / priced_qty, 2) if priced_qty else None
        out.append({
            "type_id":   m.type_id,
            "name":      m.name,
            "required":  m.required_qty,
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
    job.calc_snapshot = snap   # reassign new dict → JSON column marked dirty

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
    quantity:   Optional[int]   = None
    place:      Optional[str]   = None


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
