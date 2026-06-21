import datetime
from app.core.timeutil import utcnow
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from app.core.database import (
    get_db, Facility, FacilityFollow, Organisation, OrganisationMember, UserDB,
)
from app.core.schemas import FacilityType, Visibility
from app.core.security import get_current_user

router = APIRouter()

PUBLIC = Visibility.PUBLIC.value


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RigIn(BaseModel):
    type_id: Optional[int] = None
    name: Optional[str] = None


class FacilityCreate(BaseModel):
    name: str
    facility_type: FacilityType
    visibility: Visibility = Visibility.PRIVATE
    organisation_id: Optional[int] = None
    tax: Optional[float] = None
    cost_bonus: Optional[float] = None
    system_name: Optional[str] = None
    solar_system_id: Optional[int] = None
    system_cost_index: Optional[float] = None
    rig1: Optional[RigIn] = None
    rig2: Optional[RigIn] = None
    rig3: Optional[RigIn] = None


class FacilityUpdate(BaseModel):
    name: Optional[str] = None
    facility_type: Optional[FacilityType] = None
    visibility: Optional[Visibility] = None
    organisation_id: Optional[int] = None
    tax: Optional[float] = None
    cost_bonus: Optional[float] = None
    system_name: Optional[str] = None
    solar_system_id: Optional[int] = None
    system_cost_index: Optional[float] = None
    rig1: Optional[RigIn] = None
    rig2: Optional[RigIn] = None
    rig3: Optional[RigIn] = None


class RigOut(BaseModel):
    type_id: Optional[int] = None
    name: Optional[str] = None
class FacilityOut(BaseModel):
    id: int
    user_id: int
    organisation_id: Optional[int] = None
    name: str
    facility_type: FacilityType
    visibility: str = "private"
    owned: bool = True            # the current user owns it (vs followed/org-shared)
    following: bool = False       # the current user follows this public facility
    owner_name: Optional[str] = None
    tax: Optional[float] = None
    cost_bonus: Optional[float] = None
    system_name: Optional[str] = None
    solar_system_id: Optional[int] = None
    system_cost_index: Optional[float] = None
    rig1: RigOut
    rig2: RigOut
    rig3: RigOut
    created_at: datetime.datetime
    updated_at: Optional[datetime.datetime] = None
    class Config:
        from_attributes = True

    @classmethod
    def from_orm_model(cls, f: Facility, *, owned: bool = True, following: bool = False,
                       owner_name: Optional[str] = None) -> "FacilityOut":
        return cls(
            id=f.id, user_id=f.user_id, organisation_id=f.organisation_id, name=f.name,
            facility_type=f.facility_type, visibility=f.visibility or "private",
            owned=owned, following=following, owner_name=owner_name,
            tax=f.tax, cost_bonus=f.cost_bonus,
            system_name=f.system_name, solar_system_id=f.solar_system_id,
            system_cost_index=f.system_cost_index,
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
    # Own facilities + facilities of orgs the user is a member/owner of + followed-public
    accessible_org_ids = _accessible_org_ids(db, current_user.id)
    followed_ids = _followed_ids(db, current_user.id)
    q = db.query(Facility).filter(
        or_(
            Facility.user_id == current_user.id,
            Facility.organisation_id.in_(accessible_org_ids) if accessible_org_ids else False,
            and_(Facility.id.in_(followed_ids), Facility.visibility == PUBLIC) if followed_ids else False,
        )
    )
    if facility_type:
        q = q.filter(Facility.facility_type == facility_type)
    if organisation_id is not None:
        q = q.filter(Facility.organisation_id == organisation_id)
    rows = q.order_by(Facility.name).all()
    names = _owner_names(db, rows)
    return [
        FacilityOut.from_orm_model(
            f, owned=(f.user_id == current_user.id), following=(f.id in followed_ids),
            owner_name=names.get(f.user_id))
        for f in rows
    ]


@router.get("/public", response_model=List[FacilityOut])
async def list_public_facilities(
        facility_type: Optional[FacilityType] = None,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Public facilities created by *other* users — browse + follow to use in your calcs."""
    followed_ids = _followed_ids(db, current_user.id)
    q = db.query(Facility).filter(
        Facility.visibility == PUBLIC, Facility.user_id != current_user.id)
    if facility_type:
        q = q.filter(Facility.facility_type == facility_type)
    rows = q.order_by(Facility.name).all()
    names = _owner_names(db, rows)
    return [
        FacilityOut.from_orm_model(
            f, owned=False, following=(f.id in followed_ids), owner_name=names.get(f.user_id))
        for f in rows
    ]


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
        visibility=body.visibility.value,
        tax=body.tax,
        cost_bonus=body.cost_bonus,
        system_name=body.system_name,
        solar_system_id=body.solar_system_id,
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
    f = db.query(Facility).filter(Facility.id == facility_id).first()
    # readable if you own it, can access it (org/follow), or it's public
    if not f or (f.user_id != current_user.id and f.visibility != PUBLIC
                 and f.id not in accessible_facility_ids(db, current_user.id)):
        raise HTTPException(status_code=404, detail="Facility not found")
    following = bool(db.query(FacilityFollow).filter(
        FacilityFollow.user_id == current_user.id, FacilityFollow.facility_id == f.id).first())
    names = _owner_names(db, [f])
    return FacilityOut.from_orm_model(
        f, owned=(f.user_id == current_user.id), following=following,
        owner_name=names.get(f.user_id))


@router.post("/{facility_id}/follow", response_model=FacilityOut)
async def follow_facility(
        facility_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Add a public facility (someone else's) to your watch list so you can use it in calcs."""
    f = db.query(Facility).filter(Facility.id == facility_id).first()
    if not f or f.visibility != PUBLIC:
        raise HTTPException(status_code=404, detail="Public facility not found")
    if f.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You already own this facility")
    exists = db.query(FacilityFollow).filter(
        FacilityFollow.user_id == current_user.id, FacilityFollow.facility_id == facility_id).first()
    if not exists:
        db.add(FacilityFollow(user_id=current_user.id, facility_id=facility_id))
        db.commit()
    names = _owner_names(db, [f])
    return FacilityOut.from_orm_model(f, owned=False, following=True, owner_name=names.get(f.user_id))


@router.delete("/{facility_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow_facility(
        facility_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    db.query(FacilityFollow).filter(
        FacilityFollow.user_id == current_user.id,
        FacilityFollow.facility_id == facility_id,
    ).delete(synchronize_session=False)
    db.commit()


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
    if body.visibility is not None: f.visibility = body.visibility.value
    if body.organisation_id is not None: f.organisation_id = body.organisation_id
    if body.tax is not None: f.tax = body.tax
    if body.cost_bonus is not None: f.cost_bonus = body.cost_bonus
    if body.system_name is not None: f.system_name = body.system_name
    if body.solar_system_id is not None: f.solar_system_id = body.solar_system_id
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

    f.updated_at = utcnow()
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


def _accessible_org_ids(db: Session, user_id: int) -> set[int]:
    """Org IDs where the user is owner or an accepted member."""
    owned = {o[0] for o in db.query(Organisation.id).filter(Organisation.owner_id == user_id).all()}
    joined = {m[0] for m in db.query(OrganisationMember.org_id).filter(OrganisationMember.user_id == user_id).all()}
    return owned | joined


def _followed_ids(db: Session, user_id: int) -> set[int]:
    return {r[0] for r in db.query(FacilityFollow.facility_id).filter(
        FacilityFollow.user_id == user_id).all()}


def _owner_names(db: Session, facilities) -> dict[int, str]:
    ids = {f.user_id for f in facilities}
    if not ids:
        return {}
    return {i: n for i, n in db.query(UserDB.id, UserDB.username).filter(UserDB.id.in_(ids)).all()}


def accessible_facility_ids(db: Session, user_id: int) -> set[int]:
    """Facility IDs the user may USE in calculations: own ∪ org-shared ∪ followed-public.
    Shared with the manufacturing router so the calculator honours the same access rules."""
    own = {r[0] for r in db.query(Facility.id).filter(Facility.user_id == user_id).all()}
    org_ids = _accessible_org_ids(db, user_id)
    org_fac = ({r[0] for r in db.query(Facility.id).filter(Facility.organisation_id.in_(org_ids)).all()}
               if org_ids else set())
    followed = _followed_ids(db, user_id)
    if followed:  # only count follows that are still public
        followed = {r[0] for r in db.query(Facility.id).filter(
            Facility.id.in_(followed), Facility.visibility == PUBLIC).all()}
    return own | org_fac | followed
