import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.core.database import get_db, InventoryItem, Projects, UserDB, StockMovement
from app.core.database_eve import EveSessionLocal, EveType
from app.core.security import get_current_user

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
    project_id: Optional[int]
    eve_type_id: Optional[int]
    name: str
    volume: Optional[float]
    quantity: int
    price: Optional[float]
    place: Optional[str]
    note: Optional[str]
    flow: Optional[str] = "input"
    item_status: Optional[str] = "in_stock"
    sale_price: Optional[float] = None
    created_at: datetime.datetime
    updated_at: Optional[datetime.datetime]

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
    eve_type_id: Optional[int]
    volume: Optional[float]
    volume_total: Optional[float]
    warning: Optional[str]


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
    flow: Optional[str] = "input"   # input | output


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


def _try_int(s: str):
    try:
        return int(float(s.replace(",", "").replace(" ", "")))
    except ValueError:
        return None


def _parse_bulk_text(text: str) -> list[tuple[str, int, list[str]]]:
    """
    Parse tab-separated lines. Auto-detects two formats:
      Name\\tQty  — e.g. "Megacyte\\t8"
      Qty\\tName  — e.g. "8\\tMegacyte"
    """
    rows = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            rows.append(("", 0, [f"Line {lineno}: expected Name<tab>Qty or Qty<tab>Name, got: {repr(line)}"]))
            continue

        col0, col1 = parts[0].strip(), parts[1].strip()
        qty0, qty1 = _try_int(col0), _try_int(col1)

        if qty0 is not None and qty1 is None:
            # Qty\tName
            qty, name = qty0, col1
        elif qty0 is None and qty1 is not None:
            # Name\tQty
            name, qty = col0, qty1
        elif qty0 is not None and qty1 is not None:
            # both numeric — treat as Qty\tName (EVE multi-buy style)
            qty, name = qty0, col1
        else:
            rows.append(("", 0, [f"Line {lineno}: could not find quantity in: {repr(line)}"]))
            continue

        if qty <= 0:
            rows.append(("", 0, [f"Line {lineno}: quantity must be positive"]))
            continue
        rows.append((name, qty, []))
    return rows


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


@router.post("/batch", response_model=List[InventoryOut], status_code=status.HTTP_201_CREATED)
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


@router.post("", response_model=InventoryOut, status_code=status.HTTP_201_CREATED)
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


@router.post("/bulk", response_model=BulkParseResult, status_code=status.HTTP_201_CREATED)
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
    item_status: Optional[str] = "in_stock",   # in_stock | used | sold | all
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List inventory. Defaults to in-stock items (sold/used are hidden)."""
    q = db.query(InventoryItem).filter(InventoryItem.user_id == current_user.id)
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


def _split_off(db: Session, item: InventoryItem, qty: Optional[int]) -> InventoryItem:
    """
    Return the InventoryItem representing `qty` units to act on. If qty < the
    lot, the lot is reduced and a new detached row is created for `qty`.
    """
    take = min(int(qty or item.quantity), item.quantity)
    if take >= item.quantity:
        return item
    item.quantity -= take
    item.updated_at = datetime.datetime.utcnow()
    clone = InventoryItem(
        user_id=item.user_id, project_id=item.project_id, eve_type_id=item.eve_type_id,
        name=item.name, volume=item.volume, quantity=take, price=item.price,
        place=item.place, note=item.note, flow=item.flow,
    )
    db.add(clone)
    db.flush()
    return clone


@router.post("/{item_id}/sell", response_model=InventoryOut)
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
    target.updated_at = datetime.datetime.utcnow()
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


@router.post("/{item_id}/use", response_model=InventoryOut)
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
    target.updated_at = datetime.datetime.utcnow()
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


@router.get("/{item_id}", response_model=InventoryOut)
async def get_item(
    item_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_item_or_404(db, item_id, current_user.id)


@router.patch("/{item_id}", response_model=InventoryOut)
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

    item.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
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
