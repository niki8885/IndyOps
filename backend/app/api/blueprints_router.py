import datetime
from app.core.timeutil import utcnow
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db, Blueprint, Organisation, OrganisationMember, UserDB
from app.core.database_eve import EveSessionLocal
from app.core.security import get_current_user
from app.repositories import eve as eve_repo
from app.api.responses import ERR_400, ERR_404

router = APIRouter()


# ── schemas ────────────────────────────────────────────────────────────────────

class BlueprintIn(BaseModel):
    blueprint_type_id: int
    name: str
    organisation_id: Optional[int] = None
    is_bpo: bool = True
    me: int = 0
    te: int = 0
    runs: Optional[int] = None
    quantity: int = 1
    cost: Optional[float] = None
    facility_id: Optional[int] = None
    note: Optional[str] = None


class BlueprintUpdate(BaseModel):
    name: Optional[str] = None
    organisation_id: Optional[int] = None
    is_bpo: Optional[bool] = None
    me: Optional[int] = None
    te: Optional[int] = None
    runs: Optional[int] = None
    quantity: Optional[int] = None
    cost: Optional[float] = None
    facility_id: Optional[int] = None
    note: Optional[str] = None


class BlueprintOut(BaseModel):
    id: int
    user_id: int
    organisation_id: Optional[int] = None
    blueprint_type_id: int
    product_type_id: int
    name: str
    is_bpo: bool
    me: int
    te: int
    runs: Optional[int] = None
    quantity: int
    cost: Optional[float] = None
    facility_id: Optional[int] = None
    note: Optional[str] = None
    created_at: datetime.datetime
    updated_at: Optional[datetime.datetime] = None
    class Config:
        from_attributes = True


class ImportRow(BaseModel):
    name: str
    is_bpo: bool = True
    me: int = 0
    te: int = 0
    runs: Optional[int] = None
    quantity: int = 1
    cost: Optional[float] = None


class ImportRequest(BaseModel):
    organisation_id: Optional[int] = None
    rows: List[ImportRow]


# ── helpers ──────────────────────────────────────────────────────────────────

def _accessible_org_ids(db: Session, user_id: int) -> set[int]:
    owned = {o[0] for o in db.query(Organisation.id).filter(Organisation.owner_id == user_id).all()}
    joined = {m[0] for m in db.query(OrganisationMember.org_id).filter(OrganisationMember.user_id == user_id).all()}
    return owned | joined


def _resolve_product(eve_db, blueprint_type_id: int) -> int:
    """The product a blueprint makes, or 400 if it isn't a manufacturing/reaction BP."""
    prod = eve_repo.product_for_blueprint(eve_db, blueprint_type_id)
    if not prod:
        raise HTTPException(400, f"type_id {blueprint_type_id} is not a blueprint that makes anything")
    return prod["product_type_id"]


def _get_or_404(db: Session, bp_id: int, user_id: int) -> Blueprint:
    bp = db.query(Blueprint).filter(Blueprint.id == bp_id, Blueprint.user_id == user_id).first()
    if not bp:
        raise HTTPException(404, "Blueprint not found")
    return bp


# ── endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=List[BlueprintOut])
async def list_blueprints(
        organisation_id: Optional[int] = None,
        product_type_id: Optional[int] = None,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Own blueprints + those of orgs the user belongs to. Optionally filter to a
    product (used by the chain to offer the BPs that match each node)."""
    accessible = _accessible_org_ids(db, current_user.id)
    q = db.query(Blueprint).filter(
        or_(
            Blueprint.user_id == current_user.id,
            Blueprint.organisation_id.in_(accessible) if accessible else False,
        )
    )
    if organisation_id is not None:
        q = q.filter(Blueprint.organisation_id == organisation_id)
    if product_type_id is not None:
        q = q.filter(Blueprint.product_type_id == product_type_id)
    return q.order_by(Blueprint.name).all()


@router.post("", response_model=BlueprintOut, status_code=status.HTTP_201_CREATED, responses={**ERR_400})
async def create_blueprint(
        body: BlueprintIn,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    eve_db = EveSessionLocal()
    try:
        product_type_id = _resolve_product(eve_db, body.blueprint_type_id)
    finally:
        eve_db.close()

    bp = Blueprint(
        user_id=current_user.id, organisation_id=body.organisation_id,
        blueprint_type_id=body.blueprint_type_id, product_type_id=product_type_id,
        name=body.name, is_bpo=body.is_bpo, me=body.me, te=body.te,
        runs=None if body.is_bpo else body.runs, quantity=body.quantity,
        cost=body.cost, facility_id=body.facility_id, note=body.note,
    )
    db.add(bp)
    db.commit()
    db.refresh(bp)
    return bp


@router.patch("/{bp_id}", response_model=BlueprintOut, responses={**ERR_404})
async def update_blueprint(
        bp_id: int,
        body: BlueprintUpdate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    bp = _get_or_404(db, bp_id, current_user.id)
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(bp, field, val)
    if bp.is_bpo:
        bp.runs = None
    bp.updated_at = utcnow()
    db.commit()
    db.refresh(bp)
    return bp


@router.delete("/{bp_id}", status_code=status.HTTP_204_NO_CONTENT, responses={**ERR_404})
async def delete_blueprint(
        bp_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    db.delete(_get_or_404(db, bp_id, current_user.id))
    db.commit()


@router.post("/import")
async def import_blueprints(
        body: ImportRequest,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Bulk add from pasted rows. Resolves each name → blueprint type + product;
    rows whose name isn't a known blueprint come back in ``unresolved``."""
    eve_db = EveSessionLocal()
    try:
        resolved = eve_repo.types_by_name(eve_db, [r.name for r in body.rows])
        created, unresolved = [], []
        for r in body.rows:
            t = resolved.get(r.name.strip().lower())
            prod = eve_repo.product_for_blueprint(eve_db, t["type_id"]) if t else None
            if not t or not prod:
                unresolved.append(r.name)
                continue
            bp = Blueprint(
                user_id=current_user.id, organisation_id=body.organisation_id,
                blueprint_type_id=t["type_id"], product_type_id=prod["product_type_id"],
                name=t["name"], is_bpo=r.is_bpo, me=r.me, te=r.te,
                runs=None if r.is_bpo else r.runs, quantity=r.quantity, cost=r.cost,
            )
            db.add(bp)
            created.append(t["name"])
        db.commit()
    finally:
        eve_db.close()
    return {"created": created, "created_count": len(created), "unresolved": unresolved}
