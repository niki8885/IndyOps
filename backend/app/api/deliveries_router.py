import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.adapters import market
from app.api.inventory_router import _split_off, _get_item_or_404, _accessible_org_ids, _resolve_eve_type
from app.core.database import (
    get_db, Delivery, DeliveryStatusEvent, InventoryItem, Projects, StockMovement,
    Employee, UserDB, EsiContract, LinkedCharacter,
)
from app.core.database_eve import EveSessionLocal, EveSolarSystem
from app.core.security import get_current_user
from app.services import delivery as dsvc

router = APIRouter()

# ESI contract statuses that mean the courier delivered the goods → auto-complete.
FINISHED_STATUSES = {"finished", "finished_issuer", "finished_contractor"}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CalcRequest(BaseModel):
    mode: str = "regular"                      # regular | jf
    source_system: Optional[str] = None
    target_system: Optional[str] = None
    total_volume: float = 0.0
    total_value: Optional[float] = None
    # regular
    jumps: Optional[int] = None                # None → auto via ESI route
    isk_per_jump_m3: Optional[float] = 0.0
    # jf
    jf_ship: Optional[str] = None              # Ark | Rhea | Nomad | Anshar
    isotopes_per_ly: Optional[float] = 0.0
    isotope_price: Optional[float] = 0.0
    round_trip: bool = False


class CalcResult(BaseModel):
    mode: str
    total_volume: float
    est_cost: float
    cost_per_m3: float
    # regular
    jumps: Optional[int] = None
    jumps_auto: Optional[bool] = None
    # jf
    jf_ship: Optional[str] = None
    isotope_name: Optional[str] = None
    isotope_type_id: Optional[int] = None
    light_years: Optional[float] = None
    trips: Optional[int] = None
    total_isotopes: Optional[float] = None
    warnings: List[str] = []


class DeliveryItemIn(BaseModel):
    item_id: int
    quantity: Optional[int] = None             # None → whole lot


class DeliveryCreate(CalcRequest):
    organisation_id: Optional[int] = None
    project_id: Optional[int] = None
    source_place: Optional[str] = None
    target_place: Optional[str] = None         # where lots land; defaults to target_system
    sender_character: Optional[str] = None
    sender_employee_id: Optional[int] = None
    items: List[DeliveryItemIn] = []


class StatusUpdate(BaseModel):
    status: str                                # completed | failed


class DeliveryOut(BaseModel):
    id: int
    user_id: int
    organisation_id: Optional[int]
    project_id: Optional[int]
    source_place: Optional[str]
    source_system: Optional[str]
    target_system: Optional[str]
    target_place: Optional[str]
    mode: str
    sender_character: Optional[str]
    jumps: Optional[int]
    isk_per_jump_m3: Optional[float]
    jf_ship: Optional[str]
    isotope_name: Optional[str]
    isotope_type_id: Optional[int]
    light_years: Optional[float]
    isotopes_per_ly: Optional[float]
    trips: Optional[int]
    round_trip: bool
    isotope_price: Optional[float]
    total_isotopes: Optional[int]
    total_volume: Optional[float]
    total_value: Optional[float]
    est_cost: Optional[float]
    cost: float
    code: str
    comment: Optional[str]
    status: str
    items_snapshot: Optional[list]
    tracked: bool = False                       # a matching ESI contract exists
    contract_status: Optional[str] = None       # representative ESI contract status
    created_at: datetime.datetime
    completed_at: Optional[datetime.datetime]

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_eve_db():
    db = EveSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _resolve_system(eve_db: Session, name: Optional[str]) -> Optional[EveSolarSystem]:
    if not name:
        return None
    return (
        eve_db.query(EveSolarSystem)
        .filter(EveSolarSystem.solar_system_name.ilike(name.strip()))
        .first()
    )


def _get_delivery_or_404(db: Session, delivery_id: int, user_id: int) -> Delivery:
    d = db.query(Delivery).filter(
        Delivery.id == delivery_id, Delivery.user_id == user_id,
    ).first()
    if not d:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return d


# ── ESI-contract matching (the delivery code is embedded in the contract title) ──

def _match_contracts(db: Session, user_id: int, codes: list[str]) -> dict[str, list[EsiContract]]:
    """Map each delivery code → the user's ESI contracts whose title contains it."""
    codes = [c for c in codes if c]
    if not codes:
        return {}
    char_ids = [cid for (cid,) in db.query(LinkedCharacter.character_id).filter(
        LinkedCharacter.user_id == user_id).all()]
    if not char_ids:
        return {}
    contracts = db.query(EsiContract).filter(EsiContract.character_id.in_(char_ids)).all()
    out: dict[str, list[EsiContract]] = {}
    for c in contracts:
        title = c.title or ""
        for code in codes:
            if code in title:
                out.setdefault(code, []).append(c)
    return out


def _annotate(d: Delivery, matches: dict[str, list[EsiContract]]) -> None:
    """Attach transient `tracked` / `contract_status` to a Delivery for output."""
    found = matches.get(d.code, [])
    d.tracked = bool(found)
    if not found:
        d.contract_status = None
    elif any(c.status in FINISHED_STATUSES for c in found):
        d.contract_status = "finished"
    else:
        latest = max(found, key=lambda c: c.date_issued or datetime.datetime.min)
        d.contract_status = latest.status


def _log_status(db: Session, d: Delivery, new_status: str,
                at: datetime.datetime, note: Optional[str] = None) -> None:
    """Append a status-history row (append-only timeline of the delivery's lifecycle)."""
    db.add(DeliveryStatusEvent(
        delivery_id=d.id, from_status=d.status, status=new_status, at=at, note=note))


def _apply_complete(db: Session, d: Delivery, now: datetime.datetime) -> None:
    """Move the delivery's lots to the destination and release them."""
    target = d.target_place or d.target_system
    for lot in db.query(InventoryItem).filter(InventoryItem.delivery_id == d.id).all():
        lot.place = target
        lot.delivery_id = None
        lot.updated_at = now
    _log_status(db, d, "completed", now,
                note=f"{d.source_place or d.source_system or '?'} → {d.target_place or d.target_system or '?'}")
    d.status = "completed"
    d.completed_at = now


def _apply_fail(db: Session, d: Delivery, user_id: int, now: datetime.datetime) -> None:
    """Write off the delivery's lots (goods lost)."""
    for lot in db.query(InventoryItem).filter(InventoryItem.delivery_id == d.id).all():
        db.add(StockMovement(
            user_id=user_id, project_id=lot.project_id,
            eve_type_id=lot.eve_type_id, name=lot.name,
            quantity=lot.quantity, direction="out",
            unit_cost=lot.price, total_cost=round((lot.price or 0) * lot.quantity, 2),
            reason=f"Delivery {d.code} failed",
        ))
        db.delete(lot)
    _log_status(db, d, "failed", now, note="goods written off")
    d.status = "failed"
    d.completed_at = now


def _compute_costs(eve_db: Session, body: CalcRequest) -> dict:
    """Resolve systems / route and return the full set of cost fields + warnings."""
    out: dict = {
        "mode": body.mode, "total_volume": body.total_volume,
        "est_cost": 0.0, "cost_per_m3": 0.0, "warnings": [],
    }
    src = _resolve_system(eve_db, body.source_system)
    dst = _resolve_system(eve_db, body.target_system)

    if body.mode == "jf":
        ship = body.jf_ship
        isotope_name = dsvc.JF_ISOTOPES.get(ship) if ship else None
        out["jf_ship"] = ship
        out["isotope_name"] = isotope_name
        if isotope_name:
            iso = _resolve_eve_type(eve_db, isotope_name)
            out["isotope_type_id"] = iso.type_id if iso else None
        ly = 0.0
        if src and dst:
            ly = dsvc.light_years(src.x, src.y, src.z, dst.x, dst.y, dst.z)
        else:
            out["warnings"].append("Source/target system not found in SDE — light years = 0")
        out["light_years"] = round(ly, 3)
        jf = dsvc.jf_cost(
            body.total_volume, ly,
            body.isotopes_per_ly or 0.0, body.isotope_price or 0.0,
            round_trip=body.round_trip,
        )
        out["trips"] = jf["trips"]
        out["total_isotopes"] = jf["total_isotopes"]
        out["est_cost"] = jf["total_cost"]
        out["cost_per_m3"] = jf["cost_per_m3"]
    else:  # regular
        jumps = body.jumps
        jumps_auto = False
        if jumps is None and src and dst:
            route = market.esi_route(src.solar_system_id, dst.solar_system_id)
            if route:
                jumps = len(route) - 1
                jumps_auto = True
            else:
                out["warnings"].append("ESI route unavailable — enter jumps manually")
        if jumps is None:
            jumps = 0
        reg = dsvc.regular_cost(body.total_volume, jumps, body.isk_per_jump_m3 or 0.0)
        out["jumps"] = jumps
        out["jumps_auto"] = jumps_auto
        out["est_cost"] = reg["total_cost"]
        out["cost_per_m3"] = reg["cost_per_m3"]
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/calc", response_model=CalcResult)
async def calc(
        body: CalcRequest,
        current_user: UserDB = Depends(get_current_user),
        eve_db: Session = Depends(_get_eve_db),
):
    """Preview the shipping cost — no DB write."""
    return CalcResult(**_compute_costs(eve_db, body))


@router.get("/warehouses", response_model=List[str])
async def list_warehouses(
        organisation_id: Optional[int] = None,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Distinct, non-empty `place` values across the user's accessible inventory."""
    accessible_org_ids = _accessible_org_ids(db, current_user.id)
    org_proj_ids = (
        [pid for (pid,) in db.query(Projects.id).filter(
            Projects.organisation_id.in_(accessible_org_ids),
            Projects.deleted_at == None,  # noqa: E711
        ).all()]
        if accessible_org_ids else []
    )
    q = db.query(InventoryItem.place).filter(
        or_(
            InventoryItem.user_id == current_user.id,
            InventoryItem.project_id.in_(org_proj_ids) if org_proj_ids else False,
        ),
        InventoryItem.place.isnot(None),
    )
    if organisation_id is not None:
        proj_ids = [pid for (pid,) in db.query(Projects.id).filter(
            Projects.organisation_id == organisation_id).all()]
        q = q.filter(InventoryItem.project_id.in_(proj_ids or [-1]))
    places = {p for (p,) in q.distinct().all() if p}
    return sorted(places)


@router.post("", response_model=DeliveryOut, status_code=status.HTTP_201_CREATED)
async def create_delivery(
        body: DeliveryCreate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
        eve_db: Session = Depends(_get_eve_db),
):
    """Create a pending delivery — carve the chosen lots, compute cost, tag them."""
    if not body.items:
        raise HTTPException(status_code=400, detail="No items selected")

    # Carve exact-quantity lots out of the chosen inventory items.
    lots: list[InventoryItem] = []
    snapshot: list[dict] = []
    total_volume = 0.0
    total_value = 0.0
    for sel in body.items:
        item = _get_item_or_404(db, sel.item_id, current_user.id)
        if item.delivery_id is not None:
            raise HTTPException(status_code=400, detail=f"Item {item.id} is already in a delivery")
        lot = _split_off(db, item, sel.quantity)
        lots.append(lot)
        vol = (lot.volume or 0) * lot.quantity
        val = (lot.price or 0) * lot.quantity
        total_volume += vol
        total_value += val
        snapshot.append({
            "name": lot.name, "eve_type_id": lot.eve_type_id,
            "quantity": lot.quantity, "volume": lot.volume, "price": lot.price,
        })

    # Compute the cost using the carved total volume / value.
    calc_body = body.model_copy(update={"total_volume": total_volume, "total_value": total_value})
    costs = _compute_costs(eve_db, calc_body)

    # Project name + unique code for the comment.
    proj = db.query(Projects).filter(Projects.id == body.project_id).first() if body.project_id else None
    code = dsvc.gen_code()
    while db.query(Delivery).filter(Delivery.code == code).first():
        code = dsvc.gen_code()

    sender = body.sender_character
    if body.sender_employee_id and not sender:
        emp = db.query(Employee).filter(
            Employee.id == body.sender_employee_id, Employee.user_id == current_user.id).first()
        sender = emp.name if emp else None

    target_place = body.target_place or body.target_system
    comment = dsvc.build_comment(
        proj.name if proj else None,
        datetime.date.today().isoformat(),
        code, target_place, total_value, 0.0,
    )

    d = Delivery(
        user_id=current_user.id,
        organisation_id=body.organisation_id,
        project_id=body.project_id,
        source_place=body.source_place,
        source_system=body.source_system,
        target_system=body.target_system,
        target_place=target_place,
        mode=body.mode,
        sender_character=sender,
        sender_employee_id=body.sender_employee_id,
        jumps=costs.get("jumps"),
        isk_per_jump_m3=body.isk_per_jump_m3,
        jf_ship=costs.get("jf_ship"),
        isotope_name=costs.get("isotope_name"),
        isotope_type_id=costs.get("isotope_type_id"),
        light_years=costs.get("light_years"),
        isotopes_per_ly=body.isotopes_per_ly,
        trips=costs.get("trips"),
        round_trip=body.round_trip,
        isotope_price=body.isotope_price,
        total_isotopes=int(costs["total_isotopes"]) if costs.get("total_isotopes") else None,
        total_volume=round(total_volume, 4),
        total_value=round(total_value, 2),
        est_cost=costs.get("est_cost"),
        cost=0.0,
        code=code,
        comment=comment,
        status="pending",
        items_snapshot=snapshot,
    )
    db.add(d)
    db.flush()  # assign d.id

    for lot in lots:
        lot.delivery_id = d.id

    db.add(DeliveryStatusEvent(
        delivery_id=d.id, from_status=None, status="pending",
        at=d.created_at or datetime.datetime.utcnow(),
        note=f"created · {d.source_place or d.source_system or '?'} → {target_place or '?'}"))

    db.commit()
    db.refresh(d)
    return d


@router.get("", response_model=List[DeliveryOut])
async def list_deliveries(
        organisation_id: Optional[int] = None,
        project_id: Optional[int] = None,
        status_filter: Optional[str] = None,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    q = db.query(Delivery).filter(Delivery.user_id == current_user.id)
    if organisation_id is not None:
        q = q.filter(Delivery.organisation_id == organisation_id)
    if project_id is not None:
        q = q.filter(Delivery.project_id == project_id)
    if status_filter:
        q = q.filter(Delivery.status == status_filter)
    rows = q.order_by(Delivery.created_at.desc()).all()
    matches = _match_contracts(db, current_user.id, [d.code for d in rows])
    for d in rows:
        _annotate(d, matches)
    return rows


@router.post("/sync", response_model=List[DeliveryOut])
async def sync_contracts(
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Reconcile pending deliveries against the sender's ESI contracts.

    A pending delivery whose matching contract is *finished* is auto-completed
    (items move to target). Other contract states are left alone — too many
    situations to guess. Returns the full, annotated delivery list.
    """
    rows = db.query(Delivery).filter(
        Delivery.user_id == current_user.id).order_by(Delivery.created_at.desc()).all()
    matches = _match_contracts(db, current_user.id, [d.code for d in rows])
    now = datetime.datetime.utcnow()
    for d in rows:
        if d.status == "pending":
            found = matches.get(d.code, [])
            if any(c.status in FINISHED_STATUSES for c in found):
                _apply_complete(db, d, now)
    db.commit()
    for d in rows:
        _annotate(d, matches)
    return rows


@router.get("/{delivery_id}", response_model=DeliveryOut)
async def get_delivery(
        delivery_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    d = _get_delivery_or_404(db, delivery_id, current_user.id)
    _annotate(d, _match_contracts(db, current_user.id, [d.code]))
    return d


@router.get("/{delivery_id}/history")
async def delivery_history(
        delivery_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Status timeline for one delivery — each transition with its timestamp, plus the
    route and total elapsed time (from where, to where, how long, what changed when)."""
    d = _get_delivery_or_404(db, delivery_id, current_user.id)
    events = (db.query(DeliveryStatusEvent)
              .filter(DeliveryStatusEvent.delivery_id == d.id)
              .order_by(DeliveryStatusEvent.at).all())
    elapsed = ((d.completed_at - d.created_at).total_seconds()
               if d.completed_at and d.created_at else None)
    return {
        "delivery_id": d.id, "code": d.code,
        "source": d.source_place or d.source_system,
        "target": d.target_place or d.target_system,
        "status": d.status,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "completed_at": d.completed_at.isoformat() if d.completed_at else None,
        "elapsed_seconds": elapsed,
        "events": [
            {"from_status": e.from_status, "status": e.status,
             "at": e.at.isoformat() if e.at else None, "note": e.note}
            for e in events
        ],
    }


@router.patch("/{delivery_id}/status", response_model=DeliveryOut)
async def update_status(
        delivery_id: int,
        body: StatusUpdate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    d = _get_delivery_or_404(db, delivery_id, current_user.id)
    if d.status != "pending":
        raise HTTPException(status_code=400, detail=f"Delivery is already {d.status}")
    if body.status not in ("completed", "failed"):
        raise HTTPException(status_code=400, detail="status must be 'completed' or 'failed'")

    now = datetime.datetime.utcnow()
    if body.status == "completed":
        _apply_complete(db, d, now)
    else:
        _apply_fail(db, d, current_user.id, now)
    db.commit()
    db.refresh(d)
    return d


@router.delete("/{delivery_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_delivery(
        delivery_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Delete a delivery. A pending one releases its lots back to the warehouse."""
    d = _get_delivery_or_404(db, delivery_id, current_user.id)
    db.query(InventoryItem).filter(InventoryItem.delivery_id == d.id).update(
        {InventoryItem.delivery_id: None}, synchronize_session=False)
    db.delete(d)
    db.commit()
