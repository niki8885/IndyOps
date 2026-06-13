"""
Manufacturing calculator + Production Job (PAK) CRUD.

Activity IDs: 1=Manufacturing, 3=ResearchTE, 4=ResearchME, 5=Copying, 8=Invention
"""
import datetime
import math
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db, ProductionJob, Facility, UserDB, InventoryItem, StockMovement
from app.core.database_eve import EveSessionLocal, EveType, EveActivityMaterial, EveActivityProduct, EveActivityTime, EveBlueprint
from app.core.schemas import ProductionStatus, ProductionTarget
from app.core.security import get_current_user

router = APIRouter()

SCC_SURCHARGE = 0.04   # fixed 4% CCP surcharge on system cost


# ─────────────────────────────────────────────────────────────────────────────
# Calculation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _adj_qty(base_qty: int, runs: int, me: int) -> int:
    """Material quantity after ME reduction.  Always ≥ runs (1 unit per run min)."""
    return max(runs, math.ceil(base_qty * runs * (1 - me / 100)))


def _adj_time(base_time: int, runs: int, te: int) -> int:
    return math.ceil(base_time * runs * (1 - te / 100))


def _run_calculation(
    product_name: str,
    product_qty_per_run: int,
    runs: int,
    me: int,
    te: int,
    base_time_per_run: int,
    materials: list,           # [{type_id, name, base_qty, unit_cost}]
    output_price: float,
    bpc_cost: float,
    broker_fee_pct: float,
    system_cost_index: float,  # fraction e.g. 0.0593
    facility_tax_pct: float,
    structure_bonus_pct: float = 0.0,
    estimated_item_value: float = None,
) -> dict:

    total_output = product_qty_per_run * runs
    gross_sell   = total_output * output_price
    net_sell     = gross_sell * (1 - broker_fee_pct / 100)

    mat_rows = []
    total_mat_cost = 0.0
    for m in materials:
        adj  = _adj_qty(m["base_qty"], runs, me)
        base = m["base_qty"] * runs
        gross_cost = adj * m["unit_cost"]
        total_mat_cost += gross_cost
        mat_rows.append({
            "type_id":    m["type_id"],
            "name":       m["name"],
            "base_qty":   base,
            "adj_qty":    adj,
            "saved":      base - adj,
            "unit_cost":  m["unit_cost"],
            "gross_cost": round(gross_cost, 2),
            "net_cost":   round(gross_cost, 2),
        })

    total_mat_cost = round(total_mat_cost, 2)

    eiv = estimated_item_value if (estimated_item_value and estimated_item_value > 0) else total_mat_cost
    system_cost       = round(eiv * system_cost_index, 2)
    structure_bonus   = round(system_cost * structure_bonus_pct / 100, 2)
    gross_install     = round(system_cost - structure_bonus, 2)
    facility_tax_isk  = round(eiv * facility_tax_pct / 100, 2)
    scc_surcharge     = round(eiv * SCC_SURCHARGE, 2)
    net_install       = round(gross_install + facility_tax_isk + scc_surcharge, 2)

    job_time_s = _adj_time(base_time_per_run, runs, te)

    total_costs = round(total_mat_cost + bpc_cost + net_install, 2)
    profit      = round(net_sell - total_costs, 2)
    margin      = round(profit / total_costs * 100, 2) if total_costs else 0.0

    return {
        "output": {
            "name":      product_name,
            "quantity":  total_output,
            "unit_price": output_price,
            "gross_sell": round(gross_sell, 2),
            "net_sell":   round(net_sell, 2),
        },
        "materials": mat_rows,
        "materials_total_gross": total_mat_cost,
        "materials_total_net":   total_mat_cost,
        "job_cost": {
            "estimated_item_value": round(eiv, 2),
            "system_cost_index_pct": round(system_cost_index * 100, 4),
            "system_cost":      system_cost,
            "structure_bonus":  structure_bonus,
            "gross_install_cost": gross_install,
            "facility_tax":     facility_tax_isk,
            "scc_surcharge":    scc_surcharge,
            "net_install_cost": net_install,
        },
        "bpc_cost": bpc_cost,
        "job_time": {
            "seconds": job_time_s,
            "hours":   round(job_time_s / 3600, 2),
        },
        "results": {
            "total_material_cost": total_mat_cost,
            "total_install_cost":  net_install,
            "total_costs":   total_costs,
            "total_sell":    round(net_sell, 2),
            "profit":        profit,
            "margin_pct":    margin,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# SDE helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_blueprint_for_product(eve_db, product_type_id: int):
    """Find the manufacturing blueprint that produces this product_type_id."""
    row = (
        eve_db.query(EveActivityProduct)
        .filter(
            EveActivityProduct.product_type_id == product_type_id,
            EveActivityProduct.activity_id == 1,
        )
        .first()
    )
    return row


def _get_materials(eve_db, blueprint_type_id: int):
    rows = (
        eve_db.query(EveActivityMaterial)
        .filter(
            EveActivityMaterial.type_id == blueprint_type_id,
            EveActivityMaterial.activity_id == 1,
        )
        .all()
    )
    # enrich with names
    result = []
    for r in rows:
        t = eve_db.query(EveType).filter(EveType.type_id == r.material_type_id).first()
        result.append({
            "type_id":  r.material_type_id,
            "name":     t.type_name if t else str(r.material_type_id),
            "base_qty": r.quantity,
        })
    return result


def _get_base_time(eve_db, blueprint_type_id: int) -> int:
    row = (
        eve_db.query(EveActivityTime)
        .filter(
            EveActivityTime.type_id == blueprint_type_id,
            EveActivityTime.activity_id == 1,
        )
        .first()
    )
    return row.time if row else 0


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
    me:                   int   = 0
    te:                   int   = 0
    bpc_cost:             float = 0.0
    output_price:         float = 0.0
    broker_fee_pct:       float = 3.6
    system_cost_index:    float = 0.0    # fraction
    facility_tax_pct:     float = 0.0
    structure_bonus_pct:  float = 0.0
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
        bp_row = _get_blueprint_for_product(eve_db, product_type_id)
        if not bp_row:
            raise HTTPException(404, f"No manufacturing blueprint found for type_id {product_type_id}")

        bp_type_id   = bp_row.type_id
        qty_per_run  = bp_row.quantity
        base_time    = _get_base_time(eve_db, bp_type_id)
        materials    = _get_materials(eve_db, bp_type_id)

        bp_type = eve_db.query(EveType).filter(EveType.type_id == bp_type_id).first()
        prod_type = eve_db.query(EveType).filter(EveType.type_id == product_type_id).first()
        bp_lim = eve_db.query(EveBlueprint).filter(EveBlueprint.type_id == bp_type_id).first()

        return BlueprintInfoOut(
            blueprint_type_id=bp_type_id,
            blueprint_name=bp_type.type_name if bp_type else None,
            product_type_id=product_type_id,
            product_name=prod_type.type_name if prod_type else str(product_type_id),
            qty_per_run=qty_per_run,
            base_time_per_run=base_time,
            max_production_limit=bp_lim.max_production_limit if bp_lim else None,
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
        bp_row = _get_blueprint_for_product(eve_db, body.product_type_id)
        if not bp_row:
            raise HTTPException(404, "Blueprint not found")

        bp_type_id  = bp_row.type_id
        qty_per_run = bp_row.quantity
        base_time   = _get_base_time(eve_db, bp_type_id)
        base_mats   = _get_materials(eve_db, bp_type_id)

        prod_type = eve_db.query(EveType).filter(EveType.type_id == body.product_type_id).first()
        product_name = prod_type.type_name if prod_type else str(body.product_type_id)

    finally:
        eve_db.close()

    # merge user prices into base materials
    price_map = {p.type_id: p.unit_cost for p in body.material_prices}
    materials = [
        {**m, "unit_cost": price_map.get(m["type_id"], 0.0)}
        for m in base_mats
    ]

    # pull facility defaults if provided
    sci    = body.system_cost_index
    tax    = body.facility_tax_pct
    s_bonus = body.structure_bonus_pct
    if body.facility_id:  # override with facility values if not manually set
        f = db.query(Facility).filter(Facility.id == body.facility_id).first()
        if f:
            if sci == 0.0 and f.system_cost_index:
                sci = f.system_cost_index
            if tax == 0.0 and f.tax:
                tax = f.tax
            if s_bonus == 0.0 and f.cost_bonus:
                s_bonus = f.cost_bonus

    return _run_calculation(
        product_name=product_name,
        product_qty_per_run=qty_per_run,
        runs=body.runs,
        me=body.me,
        te=body.te,
        base_time_per_run=base_time,
        materials=materials,
        output_price=body.output_price,
        bpc_cost=body.bpc_cost,
        broker_fee_pct=body.broker_fee_pct,
        system_cost_index=sci,
        facility_tax_pct=tax,
        structure_bonus_pct=s_bonus,
        estimated_item_value=body.estimated_item_value,
    )


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
    current_user: UserDB  = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    """
    Cost-basis analysis of inventory using FIFO or LIFO costing.
    Groups items by eve_type_id (or name), returns weighted average cost and
    total value using the selected inventory costing method.
    """
    from app.core.database import InventoryItem
    from sqlalchemy import func

    q = db.query(InventoryItem).filter(InventoryItem.user_id == current_user.id)
    if project_id:
        q = q.filter(InventoryItem.project_id == project_id)

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

        remaining = need
        consumed = 0
        cost = 0.0
        for lot in lots:
            if remaining <= 0:
                break
            take = min(lot.quantity, remaining)
            cost += take * (lot.price or 0)
            consumed += take
            remaining -= take
            lot.quantity -= take
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

    if job.status in (ProductionStatus.PLANNING, ProductionStatus.PREPARING):
        job.status = ProductionStatus.IN_PROGRESS
    job.updated_at = datetime.datetime.utcnow()
    db.commit()

    return {
        "job_id": job.id,
        "total_cost": round(grand_total, 2),
        "materials": results,
        "shortfalls": [r for r in results if r["shortfall"] > 0],
    }


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
