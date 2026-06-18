import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.adapters import esi
from app.core.database import get_db, Organisation, OrganisationMember, Employee, UserDB
from app.core.schemas import EmployeeType, OrganisationType
from app.core.security import get_current_user


def corp_logo_url(corporation_id: Optional[int], size: int = 64) -> Optional[str]:
    """EVE image-server logo for a corporation id (None if no id)."""
    if not corporation_id:
        return None
    return f"https://images.evetech.net/corporations/{corporation_id}/logo?size={size}"

router = APIRouter()

# Roles that can write (edit org info, projects, packs)
WRITE_ROLES = {"OWNER", "ADMIN", "SENIOR"}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class OrganisationCreate(BaseModel):
    name: str
    org_type: OrganisationType = OrganisationType.PERSONAL
    corporation_id: Optional[int] = None
    corporation_name: Optional[str] = None
    is_public: bool = False


class OrganisationUpdate(BaseModel):
    name: Optional[str] = None
    org_type: Optional[OrganisationType] = None
    corporation_id: Optional[int] = None
    corporation_name: Optional[str] = None
    is_public: Optional[bool] = None


class OrganisationOut(BaseModel):
    id: int
    name: str
    owner_id: int
    org_type: Optional[str] = None
    corporation_id: Optional[int] = None
    corporation_name: Optional[str] = None
    corporation_logo: Optional[str] = None   # EVE image-server logo (corp orgs)
    is_public: bool = False
    created_at: datetime.datetime
    my_role: Optional[str] = None      # role of the current user in this org
    member_count: Optional[int] = None

    class Config:
        from_attributes = True


class MemberOut(BaseModel):
    user_id: int
    username: str
    role: str
    joined_at: datetime.datetime


class MemberRoleUpdate(BaseModel):
    role: str


class EmployeeCreate(BaseModel):
    name: str  # EVE character name
    character_id: Optional[int] = None
    organisation_id: Optional[int] = None
    status: EmployeeType = EmployeeType.OTHER


class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    character_id: Optional[int] = None
    organisation_id: Optional[int] = None
    status: Optional[EmployeeType] = None


class EmployeeOut(BaseModel):
    id: int
    name: str
    user_id: int
    character_id: Optional[int]
    organisation_id: Optional[int]
    status: EmployeeType
    added_at: datetime.datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_org_or_404(db: Session, org_id: int) -> Organisation:
    org = db.query(Organisation).filter(Organisation.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return org


def _get_emp_or_404(db: Session, emp_id: int) -> Employee:
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return emp


def _require_owner(org: Organisation, user: UserDB):
    if org.owner_id != user.id:
        raise HTTPException(status_code=403, detail="You are not the owner of this organisation")


def _get_member_role(db: Session, org: Organisation, user_id: int) -> Optional[str]:
    """Return the user's effective role in the org, or None if not a member."""
    if org.owner_id == user_id:
        return "OWNER"
    m = db.query(OrganisationMember).filter(
        OrganisationMember.org_id == org.id,
        OrganisationMember.user_id == user_id,
    ).first()
    return m.role if m else None


def _require_write(db: Session, org: Organisation, user: UserDB):
    role = _get_member_role(db, org, user.id)
    if role not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient role — SENIOR or above required")


def _org_out(db: Session, org: Organisation, user_id: int) -> OrganisationOut:
    role = _get_member_role(db, org, user_id)
    count = db.query(OrganisationMember).filter(OrganisationMember.org_id == org.id).count()
    return OrganisationOut(
        id=org.id, name=org.name, owner_id=org.owner_id,
        org_type=org.org_type, corporation_id=org.corporation_id,
        corporation_name=org.corporation_name,
        corporation_logo=corp_logo_url(org.corporation_id) if org.org_type == OrganisationType.CORPORATION.value else None,
        is_public=org.is_public, created_at=org.created_at,
        my_role=role, member_count=count,
    )


# ---------------------------------------------------------------------------
# Organisation CRUD
# ---------------------------------------------------------------------------

@router.post("", response_model=OrganisationOut, status_code=status.HTTP_201_CREATED)
async def create_organisation(
        body: OrganisationCreate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    if db.query(Organisation).filter(Organisation.name == body.name).first():
        raise HTTPException(status_code=400, detail="Organisation name already taken")

    org = Organisation(
        name=body.name,
        owner_id=current_user.id,
        org_type=body.org_type.value,
        corporation_id=body.corporation_id,
        corporation_name=body.corporation_name,
        is_public=body.is_public,
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return _org_out(db, org, current_user.id)


@router.patch("/{org_id}", response_model=OrganisationOut)
async def update_organisation(
        org_id: int,
        body: OrganisationUpdate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_owner(org, current_user)

    if body.name is not None:
        clash = db.query(Organisation).filter(
            Organisation.name == body.name, Organisation.id != org_id
        ).first()
        if clash:
            raise HTTPException(status_code=400, detail="Organisation name already taken")
        org.name = body.name
    if body.org_type is not None:
        org.org_type = body.org_type.value
    if body.corporation_id is not None:
        org.corporation_id = body.corporation_id
    if body.corporation_name is not None:
        org.corporation_name = body.corporation_name
    if body.is_public is not None:
        org.is_public = body.is_public

    db.commit()
    db.refresh(org)
    return _org_out(db, org, current_user.id)


@router.get("", response_model=List[OrganisationOut])
async def list_my_organisations(
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Return orgs where the user is owner OR an accepted member."""
    owned = db.query(Organisation).filter(Organisation.owner_id == current_user.id).all()
    joined_ids = {
        m.org_id for m in db.query(OrganisationMember).filter(
            OrganisationMember.user_id == current_user.id
        ).all()
    }
    # avoid duplicates (owner might also have a member record somehow)
    owned_ids = {o.id for o in owned}
    joined_orgs = db.query(Organisation).filter(
        Organisation.id.in_(joined_ids - owned_ids)
    ).all() if joined_ids - owned_ids else []

    return [_org_out(db, o, current_user.id) for o in owned + joined_orgs]


@router.get("/public", response_model=List[OrganisationOut])
async def list_public_organisations(
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """All public orgs — includes is_member flag via my_role (None = not a member)."""
    orgs = db.query(Organisation).filter(Organisation.is_public == True).order_by(Organisation.name).all()  # noqa: E712
    return [_org_out(db, o, current_user.id) for o in orgs]


@router.get("/lookup/corporation/{corporation_id}")
async def lookup_corporation(
        corporation_id: int,
        current_user: UserDB = Depends(get_current_user),
):
    """Resolve a corporation id to its public name/ticker/logo (EVE ESI)."""
    try:
        info = esi.fetch_corporation(corporation_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"Corporation {corporation_id} not found ({exc})")
    return {
        "corporation_id": corporation_id,
        "name": info.get("name"),
        "ticker": info.get("ticker"),
        "alliance_id": info.get("alliance_id"),
        "member_count": info.get("member_count"),
        "logo": corp_logo_url(corporation_id),
    }


@router.get("/{org_id}", response_model=OrganisationOut)
async def get_organisation(
        org_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    role = _get_member_role(db, org, current_user.id)
    if role is None and not org.is_public:
        raise HTTPException(status_code=403, detail="Not a member of this organisation")
    return _org_out(db, org, current_user.id)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organisation(
        org_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_owner(org, current_user)
    db.delete(org)
    db.commit()


# ---------------------------------------------------------------------------
# Membership (user ↔ org)
# ---------------------------------------------------------------------------

@router.post("/{org_id}/join", response_model=OrganisationOut)
async def join_organisation(
        org_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    if not org.is_public:
        raise HTTPException(status_code=403, detail="This organisation is not public")
    if org.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="You are already the owner")
    existing = db.query(OrganisationMember).filter(
        OrganisationMember.org_id == org_id,
        OrganisationMember.user_id == current_user.id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already a member")

    db.add(OrganisationMember(org_id=org_id, user_id=current_user.id, role="JUNIOR"))
    db.commit()
    return _org_out(db, org, current_user.id)


@router.delete("/{org_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_organisation(
        org_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    if org.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="Owner cannot leave — delete the organisation instead")
    m = db.query(OrganisationMember).filter(
        OrganisationMember.org_id == org_id,
        OrganisationMember.user_id == current_user.id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Not a member")
    db.delete(m)
    db.commit()


@router.get("/{org_id}/members", response_model=List[MemberOut])
async def list_members(
        org_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    role = _get_member_role(db, org, current_user.id)
    if role not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient role")
    rows = db.query(OrganisationMember).filter(OrganisationMember.org_id == org_id).all()
    return [
        MemberOut(
            user_id=m.user_id,
            username=m.member_user.username,
            role=m.role,
            joined_at=m.joined_at,
        )
        for m in rows
    ]


@router.patch("/{org_id}/members/{user_id}", response_model=MemberOut)
async def update_member_role(
        org_id: int,
        user_id: int,
        body: MemberRoleUpdate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_owner(org, current_user)
    m = db.query(OrganisationMember).filter(
        OrganisationMember.org_id == org_id,
        OrganisationMember.user_id == user_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Member not found")
    m.role = body.role
    db.commit()
    db.refresh(m)
    return MemberOut(user_id=m.user_id, username=m.member_user.username, role=m.role, joined_at=m.joined_at)


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def kick_member(
        org_id: int,
        user_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_owner(org, current_user)
    m = db.query(OrganisationMember).filter(
        OrganisationMember.org_id == org_id,
        OrganisationMember.user_id == user_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Member not found")
    db.delete(m)
    db.commit()


# ---------------------------------------------------------------------------
# Employees (EVE characters — owner-only)
# ---------------------------------------------------------------------------

@router.post("/{org_id}/employees", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
async def add_employee_to_org(
        org_id: int,
        body: EmployeeCreate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_owner(org, current_user)

    if db.query(Employee).filter(Employee.name == body.name).first():
        raise HTTPException(status_code=400, detail="Character name already exists")

    emp = Employee(
        name=body.name,
        user_id=current_user.id,
        character_id=body.character_id,
        organisation_id=org_id,
        status=body.status,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@router.get("/{org_id}/employees", response_model=List[EmployeeOut])
async def list_org_employees(
        org_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_owner(org, current_user)
    return db.query(Employee).filter(Employee.organisation_id == org_id).all()


@router.patch("/{org_id}/employees/{emp_id}", response_model=EmployeeOut)
async def update_employee(
        org_id: int,
        emp_id: int,
        body: EmployeeUpdate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_owner(org, current_user)

    emp = _get_emp_or_404(db, emp_id)
    if emp.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="This character does not belong to you")

    if body.name is not None:
        clash = db.query(Employee).filter(Employee.name == body.name, Employee.id != emp_id).first()
        if clash:
            raise HTTPException(status_code=400, detail="Character name already exists")
        emp.name = body.name
    if body.character_id is not None:
        emp.character_id = body.character_id
    if body.organisation_id is not None:
        target_org = db.query(Organisation).filter(Organisation.id == body.organisation_id).first()
        if not target_org or target_org.owner_id != current_user.id:
            raise HTTPException(status_code=400, detail="Target organisation not found or not yours")
        emp.organisation_id = body.organisation_id
    if body.status is not None:
        emp.status = body.status

    emp.modified_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(emp)
    return emp


@router.delete("/{org_id}/employees/{emp_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_employee(
        org_id: int,
        emp_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_owner(org, current_user)

    emp = _get_emp_or_404(db, emp_id)
    if emp.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="This character does not belong to you")

    emp.status = EmployeeType.INACTIVE
    emp.deleted_at = datetime.datetime.utcnow()
    db.commit()


# ---------------------------------------------------------------------------
# Characters (global — not org-scoped)
# ---------------------------------------------------------------------------

@router.get("/me/characters", response_model=List[EmployeeOut], tags=["characters"])
async def list_my_characters(
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    return db.query(Employee).filter(
        Employee.user_id == current_user.id,
        Employee.deleted_at == None,  # noqa: E711
    ).all()


@router.post("/me/characters", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED, tags=["characters"])
async def add_character(
        body: EmployeeCreate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    if db.query(Employee).filter(Employee.name == body.name).first():
        raise HTTPException(status_code=400, detail="Character name already exists")

    emp = Employee(
        name=body.name,
        user_id=current_user.id,
        character_id=body.character_id,
        organisation_id=body.organisation_id,
        status=body.status,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp
