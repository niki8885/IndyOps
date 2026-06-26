import datetime
import json
from app.core.timeutil import utcnow
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from app.core.database import (
    get_db, InventoryItem, Projects, Organisation, OrganisationMember, UserDB,
    StockMovement, ReprocessingPreset, LinkedCharacter, EsiAsset,
)
from sqlalchemy import or_
from app.adapters import market
from app.core.database_eve import EveSessionLocal, EveType
from app.core.security import get_current_user
from app.api.responses import ERR_400, ERR_404
from app.api.characters_router import _station_names, _system_names, _structure_names
from app.repositories import eve as eve_repo
from app.services import asset_location
from app.services.loot import parse_lines as _parse_bulk_text
from app.services.refining import RefineSetup, RigYield, compute_yield, reprocess

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class InventoryCreate(BaseModel):
    eve_type_id: Optional[int] = None
    name: str
    quantity: int
    volume: Optional[float] = None
    price: Optional[float] = None
    place: Optional[str] = None
    note: Optional[str] = None
    project_id: Optional[int] = None

    @field_validator("quantity")
    @classmethod
    def qty_positive(cls, v):
        if v <= 0:
            raise ValueError("quantity must be > 0")
        return v


class InventoryUpdate(BaseModel):
    quantity: Optional[int] = None
    price: Optional[float] = None
    place: Optional[str] = None
    note: Optional[str] = None
    project_id: Optional[int] = None

    @field_validator("quantity")
    @classmethod
    def qty_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError("quantity must be > 0")
        return v


class InventoryOut(BaseModel):
    id: int
    user_id: int
    project_id: Optional[int] = None
    eve_type_id: Optional[int] = None
    name: str
    volume: Optional[float] = None
    quantity: int
    price: Optional[float] = None
    place: Optional[str] = None
    note: Optional[str] = None
    flow: Optional[str] = "input"
    item_status: Optional[str] = "in_stock"
    sale_price: Optional[float] = None
    delivery_id: Optional[int] = None
    created_at: datetime.datetime
    updated_at: Optional[datetime.datetime] = None
    class Config:
        from_attributes = True


class BulkParseRequest(BaseModel):
    """
    Raw tab-separated text: one item per line.
    Format:  <name>\\t<quantity>
    Example:
        Water\\t3040
        Synthetic Synapses\\t6
    """
    text: str
    place: Optional[str] = None
    price: Optional[float] = None
    note: Optional[str] = None
    project_id: Optional[int] = None


class BulkParseResult(BaseModel):
    created: int
    skipped: int
    warnings: List[str]
    items: List[InventoryOut]


class PreviewItem(BaseModel):
    name: str
    quantity: int
    eve_type_id: Optional[int] = None
    volume: Optional[float] = None
    volume_total: Optional[float] = None
    warning: Optional[str] = None
class PreviewResult(BaseModel):
    items: List[PreviewItem]
    warnings: List[str]


class BatchItemCreate(BaseModel):
    eve_type_id: Optional[int] = None
    name: str
    quantity: int
    volume: Optional[float] = None
    price: Optional[float] = None
    place: Optional[str] = None
    note: Optional[str] = None
    project_id: Optional[int] = None
    flow: Optional[str] = "input"  # input | output


class BatchCreate(BaseModel):
    items: List[BatchItemCreate]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_eve_db():
    db = EveSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _resolve_eve_type(eve_db: Session, name: str) -> EveType | None:
    """Case-insensitive exact match first, then ilike fallback."""
    result = eve_db.query(EveType).filter(
        EveType.type_name.ilike(name.strip())
    ).first()
    return result


def _check_project(db: Session, project_id: int, user: UserDB) -> Projects:
    project = db.query(Projects).filter(Projects.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/preview", response_model=PreviewResult)
async def preview_bulk(
        body: BulkParseRequest,
        current_user: UserDB = Depends(get_current_user),
):
    """Parse tab-separated text and resolve EVE types — does NOT save anything."""
    rows = _parse_bulk_text(body.text)
    eve_db = EveSessionLocal()
    items: list[PreviewItem] = []
    warnings: list[str] = []

    try:
        for name, qty, row_warnings in rows:
            warnings.extend(row_warnings)
            if not name:
                continue
            eve_type = _resolve_eve_type(eve_db, name)
            vol = eve_type.volume if eve_type else None
            items.append(PreviewItem(
                name=name,
                quantity=qty,
                eve_type_id=eve_type.type_id if eve_type else None,
                volume=vol,
                volume_total=round(vol * qty, 4) if vol else None,
                warning=f"'{name}' not found in SDE" if not eve_type else None,
            ))
    finally:
        eve_db.close()

    return PreviewResult(items=items, warnings=warnings)


@router.post("/batch", response_model=List[InventoryOut], status_code=status.HTTP_201_CREATED, responses={**ERR_404})
async def batch_add(
        body: BatchCreate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Save multiple inventory items at once (used after preview + user edits)."""
    created = []
    for it in body.items:
        if it.project_id:
            _check_project(db, it.project_id, current_user)
        item = InventoryItem(
            user_id=current_user.id,
            project_id=it.project_id,
            eve_type_id=it.eve_type_id,
            name=it.name,
            volume=it.volume,
            quantity=it.quantity,
            price=it.price,
            place=it.place,
            note=it.note,
            flow=it.flow or "input",
        )
        db.add(item)
        created.append(item)
    db.commit()
    for item in created:
        db.refresh(item)
    return created


@router.post("", response_model=InventoryOut, status_code=status.HTTP_201_CREATED, responses={**ERR_404})
async def add_item(
        body: InventoryCreate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Add a single item to personal inventory."""
    if body.project_id:
        _check_project(db, body.project_id, current_user)

    eve_type_id = body.eve_type_id
    volume = body.volume

    if eve_type_id is None:
        eve_db = EveSessionLocal()
        try:
            eve_type = _resolve_eve_type(eve_db, body.name)
            if eve_type:
                eve_type_id = eve_type.type_id
                if volume is None:
                    volume = eve_type.volume
        finally:
            eve_db.close()

    item = InventoryItem(
        user_id=current_user.id,
        project_id=body.project_id,
        eve_type_id=eve_type_id,
        name=body.name,
        volume=volume,
        quantity=body.quantity,
        price=body.price,
        place=body.place,
        note=body.note,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.post("/bulk", response_model=BulkParseResult, status_code=status.HTTP_201_CREATED, responses={**ERR_404})
async def bulk_add_items(
        body: BulkParseRequest,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """
    Parse tab-separated text and add items to inventory.

    Each line: `<item name>\\t<quantity>`
    Unknown item names are stored as-is (no eve_type_id).
    """
    if body.project_id:
        _check_project(db, body.project_id, current_user)

    rows = _parse_bulk_text(body.text)
    eve_db = EveSessionLocal()

    created_items: list[InventoryItem] = []
    all_warnings: list[str] = []
    skipped = 0

    try:
        for name, qty, row_warnings in rows:
            all_warnings.extend(row_warnings)
            if not name:
                skipped += 1
                continue

            eve_type = _resolve_eve_type(eve_db, name)
            if eve_type is None:
                all_warnings.append(f"'{name}': not found in EVE SDE, stored without type link")

            item = InventoryItem(
                user_id=current_user.id,
                project_id=body.project_id,
                eve_type_id=eve_type.type_id if eve_type else None,
                name=name,
                volume=eve_type.volume if eve_type else None,
                quantity=qty,
                price=body.price,
                place=body.place,
                note=body.note,
            )
            db.add(item)
            created_items.append(item)

        db.commit()
        for item in created_items:
            db.refresh(item)

    finally:
        eve_db.close()

    return BulkParseResult(
        created=len(created_items),
        skipped=skipped,
        warnings=all_warnings,
        items=[InventoryOut.model_validate(i) for i in created_items],
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_inventory(
        project_id: Optional[int] = None,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Delete all inventory items for the current user (optionally filtered by project)."""
    q = db.query(InventoryItem).filter(InventoryItem.user_id == current_user.id)
    if project_id is not None:
        q = q.filter(InventoryItem.project_id == project_id)
    q.delete(synchronize_session=False)
    db.commit()


@router.get("", response_model=List[InventoryOut])
async def list_inventory(
        project_id: Optional[int] = None,
        organisation_id: Optional[int] = None,
        place: Optional[str] = None,
        item_status: Optional[str] = "in_stock",  # in_stock | used | sold | all
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """List inventory. Defaults to in-stock items (sold/used are hidden)."""
    # Org IDs accessible to this user (owned + member)
    accessible_org_ids = _accessible_org_ids(db, current_user.id)
    org_proj_ids = (
        [pid for (pid,) in db.query(Projects.id).filter(
            Projects.organisation_id.in_(accessible_org_ids),
            Projects.deleted_at == None,  # noqa: E711
        ).all()]
        if accessible_org_ids else []
    )

    q = db.query(InventoryItem).filter(
        or_(
            InventoryItem.user_id == current_user.id,
            InventoryItem.project_id.in_(org_proj_ids) if org_proj_ids else False,
        )
    )
    if project_id is not None:
        q = q.filter(InventoryItem.project_id == project_id)
    elif organisation_id is not None:
        proj_ids = [pid for (pid,) in db.query(Projects.id).filter(Projects.organisation_id == organisation_id).all()]
        q = q.filter(InventoryItem.project_id.in_(proj_ids or [-1]))
    if place is not None:
        q = q.filter(InventoryItem.place.ilike(f"%{place}%"))
    if item_status and item_status != "all":
        # treat legacy NULL as in_stock
        if item_status == "in_stock":
            q = q.filter((InventoryItem.item_status == "in_stock") | (InventoryItem.item_status.is_(None)))
        else:
            q = q.filter(InventoryItem.item_status == item_status)
    return q.order_by(InventoryItem.created_at.desc()).all()


class SellRequest(BaseModel):
    sale_price: float
    quantity: Optional[int] = None


class UseRequest(BaseModel):
    quantity: Optional[int] = None
    reason: Optional[str] = None


class SplitRequest(BaseModel):
    quantity: int  # units to carve off into a new stack

    @field_validator("quantity")
    @classmethod
    def qty_positive(cls, v):
        if v <= 0:
            raise ValueError("quantity must be > 0")
        return v


def _split_off(db: Session, item: InventoryItem, qty: Optional[int]) -> InventoryItem:
    """
    Return the InventoryItem representing `qty` units to act on. If qty < the
    lot, the lot is reduced and a new detached row is created for `qty`.
    """
    take = min(int(qty or item.quantity), item.quantity)
    if take >= item.quantity:
        return item
    item.quantity -= take
    item.updated_at = utcnow()
    clone = InventoryItem(
        user_id=item.user_id, project_id=item.project_id, eve_type_id=item.eve_type_id,
        name=item.name, volume=item.volume, quantity=take, price=item.price,
        place=item.place, note=item.note, flow=item.flow,
    )
    db.add(clone)
    db.flush()
    return clone


@router.post("/{item_id}/sell", response_model=InventoryOut, responses={**ERR_404})
async def sell_item(
        item_id: int,
        body: SellRequest,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Mark units sold at a sale price (for profit tracking) and remove from stock."""
    item = _get_item_or_404(db, item_id, current_user.id)
    target = _split_off(db, item, body.quantity)
    target.item_status = "sold"
    target.sale_price = body.sale_price
    target.updated_at = utcnow()
    db.add(StockMovement(
        user_id=current_user.id, project_id=target.project_id,
        eve_type_id=target.eve_type_id, name=target.name,
        quantity=target.quantity, direction="out",
        unit_cost=body.sale_price, total_cost=round(body.sale_price * target.quantity, 2),
        reason="Sold",
    ))
    db.commit()
    db.refresh(target)
    return target


@router.post("/{item_id}/split", response_model=List[InventoryOut], responses={**ERR_400, **ERR_404})
async def split_item(
        item_id: int,
        body: SplitRequest,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Split a lot into two stacks: the original keeps the remainder, a new lot
    holds `quantity`. Returns [original, new]."""
    item = _get_item_or_404(db, item_id, current_user.id)
    if item.delivery_id is not None:
        raise HTTPException(status_code=400, detail="Item is reserved by a delivery — cannot split")
    if body.quantity >= item.quantity:
        raise HTTPException(status_code=400, detail=f"Split quantity must be less than {item.quantity}")

    clone = _split_off(db, item, body.quantity)
    clone.item_status = item.item_status  # _split_off defaults to in_stock; keep source status
    db.commit()
    db.refresh(item)
    db.refresh(clone)
    return [item, clone]


@router.post("/{item_id}/use", response_model=InventoryOut, responses={**ERR_404})
async def use_item(
        item_id: int,
        body: UseRequest,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Write units off for internal use (e.g. refueling) and remove from stock."""
    item = _get_item_or_404(db, item_id, current_user.id)
    target = _split_off(db, item, body.quantity)
    target.item_status = "used"
    target.updated_at = utcnow()
    db.add(StockMovement(
        user_id=current_user.id, project_id=target.project_id,
        eve_type_id=target.eve_type_id, name=target.name,
        quantity=target.quantity, direction="out",
        unit_cost=target.price, total_cost=round((target.price or 0) * target.quantity, 2),
        reason=f"Used: {body.reason}" if body.reason else "Used (internal)",
    ))
    db.commit()
    db.refresh(target)
    return target


@router.get("/{item_id}", response_model=InventoryOut, responses={**ERR_404})
async def get_item(
        item_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    return _get_item_or_404(db, item_id, current_user.id)


@router.patch("/{item_id}", response_model=InventoryOut, responses={**ERR_404})
async def update_item(
        item_id: int,
        body: InventoryUpdate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    item = _get_item_or_404(db, item_id, current_user.id)

    if body.project_id is not None:
        _check_project(db, body.project_id, current_user)
        item.project_id = body.project_id
    if body.quantity is not None:
        item.quantity = body.quantity
    if body.price is not None:
        item.price = body.price
    if body.place is not None:
        item.place = body.place
    if body.note is not None:
        item.note = body.note

    item.updated_at = utcnow()
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT, responses={**ERR_404})
async def delete_item(
        item_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    item = _get_item_or_404(db, item_id, current_user.id)
    db.delete(item)
    db.commit()


# ---------------------------------------------------------------------------
# Private
# ---------------------------------------------------------------------------

def _get_item_or_404(db: Session, item_id: int, user_id: int) -> InventoryItem:
    item = db.query(InventoryItem).filter(
        InventoryItem.id == item_id,
        InventoryItem.user_id == user_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return item


def _accessible_org_ids(db: Session, user_id: int) -> set[int]:
    """Org IDs where the user is owner or an accepted member."""
    owned = {o[0] for o in db.query(Organisation.id).filter(Organisation.owner_id == user_id).all()}
    joined = {m[0] for m in db.query(OrganisationMember.org_id).filter(OrganisationMember.user_id == user_id).all()}
    return owned | joined


# ---------------------------------------------------------------------------
# Reprocessing — saved presets + refine warehouse ore into minerals
# ---------------------------------------------------------------------------

JITA_REGION = 10000002       # The Forge — mineral valuation hub for cost allocation
_ORE_CATEGORY = 25           # invCategories: asteroid (ore / ice / moon ore)


def _build_rigs(eve_db: Session, rig_type_ids: list) -> tuple:
    """Resolve reprocessing-yield rig type ids → ``RigYield`` from the SDE catalog."""
    if not rig_type_ids:
        return ()
    catalog = {r["type_id"]: r for r in eve_repo.reprocessing_rigs(eve_db)}
    rigs = []
    for rid in rig_type_ids:
        r = catalog.get(rid)
        if r and r.get("yield_bonus"):
            rigs.append(RigYield(
                name=r["name"], yield_bonus=r["yield_bonus"],
                hisec_mod=r.get("hisec_mod", 1.0), lowsec_mod=r.get("lowsec_mod", 1.9),
                nullsec_mod=r.get("nullsec_mod", 2.1)))
    return tuple(rigs)


def _basis_price(two: dict, basis: str):
    b, s = two.get("buy"), two.get("sell")
    if basis == "split":
        if b is not None and s is not None:
            return (b + s) / 2
        return b if b is not None else s
    return two.get(basis)


def _jita_two_sided(type_ids: list) -> dict:
    """Per-type ``{'buy','sell'}`` from Jita (Fuzzwork aggregates), for cost allocation."""
    agg = market.fuzzwork_aggregates_or_empty(JITA_REGION, type_ids)
    out = {}
    for tid in type_ids:
        s = agg.get(str(tid)) or {}
        b, se = s.get("buy") or {}, s.get("sell") or {}
        out[tid] = {"buy": b.get("percentile") or b.get("max"),
                    "sell": se.get("percentile") or se.get("min")}
    return out


class PresetIn(BaseModel):
    name: str
    structure_type: Optional[str] = None       # npc_station | athanor | tatara (drives base_yield)
    base_yield: float = 0.50
    tax_pct: float = 0.0
    security: str = "hi"
    reprocessing_lvl: int = 0
    efficiency_lvl: int = 0
    ore_specific_lvl: int = 0
    implant_pct: float = 0.0
    rig_type_ids: List[int] = []


# Structure base yields — keep in sync with refining.BASE_YIELD_PRESETS. When a preset
# names a known structure, its base yield is authoritative (the user can't fat-finger it).
_STRUCTURE_BASE = {"npc_station": 0.50, "athanor": 0.50, "tatara": 0.55}


def _preset_out(p: ReprocessingPreset) -> dict:
    return {
        "id": p.id, "name": p.name, "structure_type": p.structure_type,
        "base_yield": p.base_yield, "tax_pct": p.tax_pct,
        "security": p.security, "reprocessing_lvl": p.reprocessing_lvl,
        "efficiency_lvl": p.efficiency_lvl, "ore_specific_lvl": p.ore_specific_lvl,
        "implant_pct": p.implant_pct,
        "rig_type_ids": json.loads(p.rig_type_ids) if p.rig_type_ids else [],
    }


def _apply_preset(p: ReprocessingPreset, body: PresetIn) -> None:
    p.name = (body.name or "").strip()[:80] or "Preset"
    st = body.structure_type if body.structure_type in _STRUCTURE_BASE else None
    p.structure_type = st
    # a known structure type sets the base yield authoritatively; otherwise take the
    # manual value (custom NPC stations / unusual setups).
    p.base_yield = _STRUCTURE_BASE[st] if st else min(1.0, max(0.0, body.base_yield))
    p.tax_pct = max(0.0, body.tax_pct)
    p.security = body.security if body.security in ("hi", "low", "null") else "hi"
    p.reprocessing_lvl = max(0, min(5, body.reprocessing_lvl))
    p.efficiency_lvl = max(0, min(5, body.efficiency_lvl))
    p.ore_specific_lvl = max(0, min(5, body.ore_specific_lvl))
    p.implant_pct = max(0.0, body.implant_pct)
    p.rig_type_ids = json.dumps(sorted({int(r) for r in (body.rig_type_ids or [])}))


@router.get("/reprocessing/presets")
async def list_presets(current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(ReprocessingPreset).filter(ReprocessingPreset.user_id == current_user.id)
            .order_by(ReprocessingPreset.name).all())
    return [_preset_out(p) for p in rows]


@router.post("/reprocessing/presets", status_code=status.HTTP_201_CREATED)
async def create_preset(body: PresetIn, current_user: UserDB = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    p = ReprocessingPreset(user_id=current_user.id, created_at=utcnow())
    _apply_preset(p, body)
    db.add(p)
    db.commit()
    db.refresh(p)
    return _preset_out(p)


@router.put("/reprocessing/presets/{preset_id}", responses={**ERR_404})
async def update_preset(preset_id: int, body: PresetIn,
                        current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    p = (db.query(ReprocessingPreset)
         .filter(ReprocessingPreset.id == preset_id, ReprocessingPreset.user_id == current_user.id).first())
    if not p:
        raise HTTPException(404, "Preset not found")
    _apply_preset(p, body)
    p.updated_at = utcnow()
    db.commit()
    db.refresh(p)
    return _preset_out(p)


@router.delete("/reprocessing/presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT, responses={**ERR_404})
async def delete_preset(preset_id: int, current_user: UserDB = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    p = (db.query(ReprocessingPreset)
         .filter(ReprocessingPreset.id == preset_id, ReprocessingPreset.user_id == current_user.id).first())
    if not p:
        raise HTTPException(404, "Preset not found")
    db.delete(p)
    db.commit()


@router.get("/reprocessing/stock")
async def reprocessing_stock(current_user: UserDB = Depends(get_current_user),
                             db: Session = Depends(get_db), eve_db: Session = Depends(_get_eve_db)):
    """In-stock ore lots (asteroid category, with reprocessing yields) the user can refine."""
    items = (db.query(InventoryItem)
             .filter(InventoryItem.user_id == current_user.id,
                     InventoryItem.item_status == "in_stock", InventoryItem.flow == "input",
                     InventoryItem.eve_type_id.isnot(None), InventoryItem.delivery_id.is_(None)).all())
    type_ids = list({i.eve_type_id for i in items if i.eve_type_id})
    yields = eve_repo.reprocessing_yields(eve_db, type_ids)
    groups = eve_repo.type_groups(eve_db, type_ids)
    out = []
    for i in items:
        g = groups.get(i.eve_type_id) or {}
        if i.eve_type_id in yields and g.get("category_id") == _ORE_CATEGORY:
            out.append({"id": i.id, "type_id": i.eve_type_id, "name": i.name,
                        "quantity": int(i.quantity or 0), "price": i.price, "place": i.place})
    return sorted(out, key=lambda x: x["name"])


def _asset_location_name(roots: dict, item_id, names_by_kind: dict, fallback_loc):
    """Resolve one asset's terminus to ``(location_id, location_name)`` for grouping."""
    kind, rid = roots.get(item_id, (None, None))
    if kind == "station":
        return rid, names_by_kind["station"].get(rid) or f"Station #{rid}"
    if kind == "system":
        return rid, names_by_kind["system"].get(rid) or f"System #{rid}"
    if kind == "structure":
        return rid, names_by_kind["structure"].get(rid) or f"Structure #{rid}"
    return (fallback_loc or 0), (f"#{fallback_loc}" if fallback_loc else "Unknown location")


@router.get("/reprocessing/assets")
async def reprocessing_assets(current_user: UserDB = Depends(get_current_user),
                              db: Session = Depends(get_db), eve_db: Session = Depends(_get_eve_db)):
    """Ore the user actually holds in-game, read live from synced ESI assets and grouped by
    the station/structure that holds it. Each asset's location chain is walked to its real
    terminus (ore nested in a ship/container resolves to the dock), so the Reprocess panel can
    offer a location picker + per-station ore list without a manual inventory import."""
    char_ids = [c.character_id for c in
                db.query(LinkedCharacter).filter(LinkedCharacter.user_id == current_user.id).all()]
    assets = db.query(EsiAsset).filter(EsiAsset.character_id.in_(char_ids or [-1])).all()
    if not assets:
        return {"locations": [], "ore": []}

    type_ids = list({a.type_id for a in assets if a.type_id})
    yields = eve_repo.reprocessing_yields(eve_db, type_ids)
    groups = eve_repo.type_groups(eve_db, type_ids)
    ore_ids = {tid for tid in type_ids
               if tid in yields and (groups.get(tid) or {}).get("category_id") == _ORE_CATEGORY}
    if not ore_ids:
        return {"locations": [], "ore": []}

    names = eve_repo.type_names(eve_db, list(ore_ids))
    roots, by_kind = asset_location.terminus_ids(assets)
    names_by_kind = {
        "station": _station_names(eve_db, by_kind["station"]),
        "system": _system_names(eve_db, by_kind["system"]),
        "structure": _structure_names(db, by_kind["structure"]),
    }

    agg: dict = {}          # (location_id, type_id) -> summed quantity
    loc_name: dict = {}
    for a in assets:
        if a.type_id not in ore_ids:
            continue
        loc_id, name = _asset_location_name(roots, a.item_id, names_by_kind, a.location_id)
        loc_name[loc_id] = name
        agg[(loc_id, a.type_id)] = agg.get((loc_id, a.type_id), 0) + int(a.quantity or 0)

    sides = _jita_two_sided(list({tid for _, tid in agg}))
    ore, loc_summary = [], {}
    for (loc_id, tid), qty in agg.items():
        price = _basis_price(sides.get(tid) or {}, "sell")
        ore.append({"type_id": tid, "name": names.get(tid) or str(tid), "quantity": qty,
                    "location_id": loc_id, "location_name": loc_name.get(loc_id),
                    "price": round(price, 2) if price else None})
        ls = loc_summary.setdefault(loc_id, {"id": loc_id, "name": loc_name.get(loc_id),
                                             "ore_types": 0, "total_qty": 0})
        ls["ore_types"] += 1
        ls["total_qty"] += qty

    ore.sort(key=lambda x: ((x["location_name"] or "~"), x["name"]))
    locations = sorted(loc_summary.values(), key=lambda x: (x["name"] or "~"))
    return {"locations": locations, "ore": ore}


class ReprocessLine(BaseModel):
    type_id: int
    quantity: int


class ReprocessPreviewIn(BaseModel):
    preset_id: int
    lines: List[ReprocessLine] = []
    basis: str = "sell"               # Jita basis for the mineral + raw-ore valuation


@router.post("/reprocessing/preview", responses={**ERR_400, **ERR_404})
async def reprocess_preview(body: ReprocessPreviewIn, current_user: UserDB = Depends(get_current_user),
                            db: Session = Depends(get_db), eve_db: Session = Depends(_get_eve_db)):
    """Refine a selection of ore (type_id × quantity, e.g. picked from a station's live
    assets) through a saved preset and return the resulting minerals + Jita value — a
    read-only calculator. Reports the raw-ore Jita value alongside, so the refine premium
    (``delta``) answers "should I reprocess or sell the ore as-is?". Mutates nothing."""
    preset = (db.query(ReprocessingPreset)
              .filter(ReprocessingPreset.id == body.preset_id, ReprocessingPreset.user_id == current_user.id).first())
    if not preset:
        raise HTTPException(404, "Preset not found")
    lines = [l for l in body.lines if l.type_id and l.quantity > 0]
    if not lines:
        raise HTTPException(400, "No ore selected")

    rigs = _build_rigs(eve_db, json.loads(preset.rig_type_ids) if preset.rig_type_ids else [])
    ry = compute_yield(RefineSetup(
        base_yield=preset.base_yield, reprocessing_lvl=preset.reprocessing_lvl,
        efficiency_lvl=preset.efficiency_lvl, ore_specific_lvl=preset.ore_specific_lvl,
        implant_pct=preset.implant_pct, rigs=rigs, security=preset.security, tax_pct=preset.tax_pct))

    type_ids = [l.type_id for l in lines]
    yields = eve_repo.reprocessing_yields(eve_db, type_ids)
    ore_names = eve_repo.type_names(eve_db, type_ids)
    ore_sides = _jita_two_sided(type_ids)
    minerals: dict = {}
    raw_ore_value = 0.0
    skipped: list = []
    for l in lines:
        info = yields.get(l.type_id)
        res = (reprocess(int(l.quantity), info["portion_size"], info["materials"], ry,
                         input_type_id=l.type_id) if info and info["materials"] else None)
        if not res or not res.minerals or res.refined_units <= 0:
            skipped.append(ore_names.get(l.type_id) or str(l.type_id))
            continue
        for mn in res.minerals:
            minerals[mn.type_id] = minerals.get(mn.type_id, 0) + mn.qty
        raw_ore_value += (_basis_price(ore_sides.get(l.type_id) or {}, body.basis) or 0.0) * res.refined_units
    if not minerals:
        raise HTTPException(400, "Nothing reprocessable in the selection (need at least one full batch of ore)")

    mineral_ids = list(minerals)
    sides = _jita_two_sided(mineral_ids)
    names = eve_repo.type_names(eve_db, mineral_ids)
    out, total_value = [], 0.0
    for tid, qty in minerals.items():
        unit = _basis_price(sides.get(tid) or {}, body.basis) or 0.0
        out.append({"type_id": tid, "name": names.get(tid) or str(tid), "quantity": qty,
                    "unit_cost": round(unit, 2), "value": round(unit * qty, 2)})
        total_value += unit * qty

    return {
        "preset": preset.name,
        "effective_yield": ry.effective_yield,
        "raw_ore_value": round(raw_ore_value, 2),
        "total_value": round(total_value, 2),
        "delta": round(total_value - raw_ore_value, 2),
        "minerals": sorted(out, key=lambda x: -x["value"]),
        "skipped": skipped,
    }


class ReprocessIn(BaseModel):
    preset_id: int
    item_ids: List[int] = []
    basis: str = "sell"               # Jita basis for allocating ore cost across minerals
    place: Optional[str] = None       # where to store the resulting minerals


@router.post("/reprocessing/reprocess", responses={**ERR_400, **ERR_404})
async def reprocess_inventory(body: ReprocessIn, current_user: UserDB = Depends(get_current_user),
                              db: Session = Depends(get_db), eve_db: Session = Depends(_get_eve_db)):
    """Refine selected warehouse ore lots into minerals using a saved preset. The ore's
    cost basis is carried onto the minerals (allocated by Jita value) and the lots are
    marked ``source="reprocess"`` so the Industry tracker treats them as owned cost basis."""
    preset = (db.query(ReprocessingPreset)
              .filter(ReprocessingPreset.id == body.preset_id, ReprocessingPreset.user_id == current_user.id).first())
    if not preset:
        raise HTTPException(404, "Preset not found")
    items = (db.query(InventoryItem)
             .filter(InventoryItem.id.in_(body.item_ids or [-1]), InventoryItem.user_id == current_user.id,
                     InventoryItem.item_status == "in_stock", InventoryItem.delivery_id.is_(None)).all())
    if not items:
        raise HTTPException(400, "No in-stock lots selected")

    rigs = _build_rigs(eve_db, json.loads(preset.rig_type_ids) if preset.rig_type_ids else [])
    ry = compute_yield(RefineSetup(
        base_yield=preset.base_yield, reprocessing_lvl=preset.reprocessing_lvl,
        efficiency_lvl=preset.efficiency_lvl, ore_specific_lvl=preset.ore_specific_lvl,
        implant_pct=preset.implant_pct, rigs=rigs, security=preset.security, tax_pct=preset.tax_pct))

    yields = eve_repo.reprocessing_yields(eve_db, [i.eve_type_id for i in items if i.eve_type_id])
    minerals: dict = {}
    ore_cost = 0.0
    consumed: list = []
    skipped: list = []
    for i in items:
        info = yields.get(i.eve_type_id)
        res = (reprocess(int(i.quantity or 0), info["portion_size"], info["materials"], ry,
                         input_type_id=i.eve_type_id) if info and info["materials"] else None)
        if not res or not res.minerals or res.refined_units <= 0:
            skipped.append(i.name)
            continue
        for mn in res.minerals:
            minerals[mn.type_id] = minerals.get(mn.type_id, 0) + mn.qty
        ore_cost += (i.price or 0.0) * res.refined_units
        consumed.append((i, res))
    if not minerals:
        raise HTTPException(400, "Nothing reprocessable in the selection (need at least one full batch of ore)")

    mineral_ids = list(minerals)
    sides = _jita_two_sided(mineral_ids)
    names = eve_repo.type_names(eve_db, mineral_ids)
    vols = eve_repo.volumes(eve_db, mineral_ids)
    values = {tid: (_basis_price(sides.get(tid) or {}, body.basis) or 0.0) * qty for tid, qty in minerals.items()}
    total_value = sum(values.values())

    now = utcnow()
    place = body.place or next((i.place for i, _ in consumed if i.place), None)
    project_id = consumed[0][0].project_id if consumed else None

    for i, res in consumed:
        if res.refined_units >= (i.quantity or 0):
            i.item_status = "used"
        else:
            i.quantity = (i.quantity or 0) - res.refined_units
        i.updated_at = now
        db.add(StockMovement(
            user_id=current_user.id, project_id=i.project_id, eve_type_id=i.eve_type_id,
            name=i.name, quantity=res.refined_units, direction="out", unit_cost=i.price,
            total_cost=round((i.price or 0.0) * res.refined_units, 2), reason=f"Reprocessed ({preset.name})"))

    created = []
    for tid, qty in minerals.items():
        share = (values[tid] / total_value) if total_value > 0 else (1.0 / len(minerals))
        unit_cost = round((ore_cost * share) / qty, 4) if qty else 0.0
        item = InventoryItem(
            user_id=current_user.id, project_id=project_id, eve_type_id=tid,
            name=names.get(tid, str(tid)), volume=vols.get(tid), quantity=qty, price=unit_cost,
            place=place, flow="input", source="reprocess", note=f"Reprocessed via {preset.name}",
            created_at=now)
        db.add(item)
        created.append({"type_id": tid, "name": names.get(tid, str(tid)), "quantity": qty,
                        "unit_cost": unit_cost, "value": round(values[tid], 2)})
    db.commit()

    return {
        "preset": preset.name,
        "effective_yield": ry.effective_yield,
        "ore_cost": round(ore_cost, 2),
        "total_value": round(total_value, 2),
        "minerals": sorted(created, key=lambda x: -x["value"]),
        "skipped": skipped,
    }
