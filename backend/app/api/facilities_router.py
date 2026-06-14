import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db, Facility, UserDB
from app.core.schemas import FacilityType
from app.core.security import get_current_user

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RigIn(BaseModel):
    type_id: Optional[int] = None
    name: Optional[str] = None


class FacilityCreate(BaseModel):
    name: str
    facility_type: FacilityType
    organisation_id: Optional[int] = None
    tax: Optional[float] = None
    cost_bonus: Optional[float] = None
    system_name: Optional[str] = None
    system_cost_index: Optional[float] = None
    rig1: Optional[RigIn] = None
    rig2: Optional[RigIn] = None
    rig3: Optional[RigIn] = None


class FacilityUpdate(BaseModel):
    name: Optional[str] = None
    facility_type: Optional[FacilityType] = None
    organisation_id: Optional[int] = None
    tax: Optional[float] = None
    cost_bonus: Optional[float] = None
    system_name: Optional[str] = None
    system_cost_index: Optional[float] = None
    rig1: Optional[RigIn] = None
    rig2: Optional[RigIn] = None
    rig3: Optional[RigIn] = None


class RigOut(BaseModel):
    type_id: Optional[int]
    name: Optional[str]


class FacilityOut(BaseModel):
    id: int
    user_id: int
    organisation_id: Optional[int]
    name: str
    facility_type: FacilityType
    tax: Optional[float]
    cost_bonus: Optional[float]
    system_name: Optional[str]
    system_cost_index: Optional[float]
    rig1: RigOut
    rig2: RigOut
    rig3: RigOut
    created_at: datetime.datetime
    updated_at: Optional[datetime.datetime]

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_model(cls, f: Facility) -> "FacilityOut":
        return cls(
            id=f.id, user_id=f.user_id, organisation_id=f.organisation_id, name=f.name,
            facility_type=f.facility_type,
            tax=f.tax, cost_bonus=f.cost_bonus,
            system_name=f.system_name, system_cost_index=f.system_cost_index,
            rig1=RigOut(type_id=f.rig1_type_id, name=f.rig1_name),
            rig2=RigOut(type_id=f.rig2_type_id, name=f.rig2_name),
            rig3=RigOut(type_id=f.rig3_type_id, name=f.rig3_name),
            created_at=f.created_at, updated_at=f.updated_at,
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=List[FacilityOut])
async def list_facilities(
        facility_type: Optional[FacilityType] = None,
        organisation_id: Optional[int] = None,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    q = db.query(Facility).filter(Facility.user_id == current_user.id)
    if facility_type:
        q = q.filter(Facility.facility_type == facility_type)
    if organisation_id is not None:
        q = q.filter(Facility.organisation_id == organisation_id)
    return [FacilityOut.from_orm_model(f) for f in q.order_by(Facility.name).all()]


@router.post("", response_model=FacilityOut, status_code=status.HTTP_201_CREATED)
async def create_facility(
        body: FacilityCreate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    f = Facility(
        user_id=current_user.id,
        organisation_id=body.organisation_id,
        name=body.name,
        facility_type=body.facility_type,
        tax=body.tax,
        cost_bonus=body.cost_bonus,
        system_name=body.system_name,
        system_cost_index=body.system_cost_index,
        rig1_type_id=body.rig1.type_id if body.rig1 else None,
        rig1_name=body.rig1.name if body.rig1 else None,
        rig2_type_id=body.rig2.type_id if body.rig2 else None,
        rig2_name=body.rig2.name if body.rig2 else None,
        rig3_type_id=body.rig3.type_id if body.rig3 else None,
        rig3_name=body.rig3.name if body.rig3 else None,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return FacilityOut.from_orm_model(f)


@router.get("/{facility_id}", response_model=FacilityOut)
async def get_facility(
        facility_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    return FacilityOut.from_orm_model(_get_or_404(db, facility_id, current_user.id))


@router.patch("/{facility_id}", response_model=FacilityOut)
async def update_facility(
        facility_id: int,
        body: FacilityUpdate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    f = _get_or_404(db, facility_id, current_user.id)

    if body.name is not None: f.name = body.name
    if body.facility_type is not None: f.facility_type = body.facility_type
    if body.organisation_id is not None: f.organisation_id = body.organisation_id
    if body.tax is not None: f.tax = body.tax
    if body.cost_bonus is not None: f.cost_bonus = body.cost_bonus
    if body.system_name is not None: f.system_name = body.system_name
    if body.system_cost_index is not None: f.system_cost_index = body.system_cost_index

    if body.rig1 is not None:
        f.rig1_type_id = body.rig1.type_id
        f.rig1_name = body.rig1.name
    if body.rig2 is not None:
        f.rig2_type_id = body.rig2.type_id
        f.rig2_name = body.rig2.name
    if body.rig3 is not None:
        f.rig3_type_id = body.rig3.type_id
        f.rig3_name = body.rig3.name

    f.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(f)
    return FacilityOut.from_orm_model(f)


@router.delete("/{facility_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_facility(
        facility_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    f = _get_or_404(db, facility_id, current_user.id)
    db.delete(f)
    db.commit()


# ---------------------------------------------------------------------------

def _get_or_404(db: Session, facility_id: int, user_id: int) -> Facility:
    f = db.query(Facility).filter(
        Facility.id == facility_id,
        Facility.user_id == user_id,
    ).first()
    if not f:
        raise HTTPException(status_code=404, detail="Facility not found")
    return f
