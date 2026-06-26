import datetime
from app.core.timeutil import utcnow
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.adapters import esi
from app.core.database import (
    get_db, Organisation, OrganisationFollow, OrganisationMember, Employee, UserDB,
    LinkedCharacter, CorpTrackingPref, EsiCorpWallet, EsiCorpIndustryJob, EsiCorpMember,
)
from app.core.database_eve import EveSessionLocal, EveSolarSystem, EveStation, EveType
from app.core.schemas import EmployeeType, OrganisationType, Visibility
from app.core.security import get_current_user
from app.api.responses import ERR_400, ERR_403, ERR_404

PUBLIC = Visibility.PUBLIC.value


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
    visibility: Optional[Visibility] = None   # preferred; is_public kept in sync


class OrganisationUpdate(BaseModel):
    name: Optional[str] = None
    org_type: Optional[OrganisationType] = None
    corporation_id: Optional[int] = None
    corporation_name: Optional[str] = None
    is_public: Optional[bool] = None
    visibility: Optional[Visibility] = None


class OrganisationOut(BaseModel):
    id: int
    name: str
    owner_id: int
    org_type: Optional[str] = None
    corporation_id: Optional[int] = None
    corporation_name: Optional[str] = None
    corporation_logo: Optional[str] = None   # EVE image-server logo (corp orgs)
    is_public: bool = False
    visibility: str = "private"
    following: bool = False            # the current user follows (watches) this public org
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
    character_id: Optional[int] = None
    organisation_id: Optional[int] = None
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


_CORP = OrganisationType.CORPORATION.value

# Corp-ESI (Phase B) access gating — mirrors update_esi role/scope constants.
_SC_CORP_WALLET = "esi-wallet.read_corporation_wallets.v1"
_SC_CORP_JOBS = "esi-industry.read_corporation_jobs.v1"
_SC_CORP_MEMBERS = "esi-corporations.read_corporation_membership.v1"
_R_ACCOUNTANT = {"Director", "Accountant", "Junior_Accountant"}
_R_FACTORY = {"Director", "Factory_Manager"}
_CORP_ACT = {1: "Manufacturing", 3: "TE Research", 4: "ME Research", 5: "Copying",
             7: "Reverse Engineering", 8: "Invention", 9: "Reactions", 11: "Reactions"}
_CORP_JOB_ACTIVE = {"active", "ready", "paused"}


def _char_has_scope(ch, scope) -> bool:
    return scope in (ch.scopes or "").split()


def _user_corp_ids(db: Session, user_id: int) -> set:
    """Distinct EVE corporation ids across the user's linked characters."""
    return {cid for (cid,) in db.query(LinkedCharacter.corporation_id)
            .filter(LinkedCharacter.user_id == user_id, LinkedCharacter.corporation_id.isnot(None))
            .distinct()}


def _get_member_role(db: Session, org: Organisation, user_id: int) -> Optional[str]:
    """Return the user's effective role in the org, or None if not a member.

    For a Corporation org, a user with a linked character in that corporation is an
    *auto-derived* read-only member ("MEMBER" — deliberately NOT in WRITE_ROLES, so being
    in the corp never grants edit rights)."""
    if org.owner_id == user_id:
        return "OWNER"
    m = db.query(OrganisationMember).filter(
        OrganisationMember.org_id == org.id,
        OrganisationMember.user_id == user_id,
    ).first()
    if m:
        return m.role
    if org.org_type == _CORP and org.corporation_id and org.corporation_id in _user_corp_ids(db, user_id):
        return "MEMBER"
    return None


def _require_write(db: Session, org: Organisation, user: UserDB):
    role = _get_member_role(db, org, user.id)
    if role not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient role — SENIOR or above required")


def _org_out(db: Session, org: Organisation, user_id: int) -> OrganisationOut:
    role = _get_member_role(db, org, user_id)
    count = db.query(OrganisationMember).filter(OrganisationMember.org_id == org.id).count()
    following = bool(db.query(OrganisationFollow).filter(
        OrganisationFollow.user_id == user_id, OrganisationFollow.org_id == org.id).first())
    return OrganisationOut(
        id=org.id, name=org.name, owner_id=org.owner_id,
        org_type=org.org_type, corporation_id=org.corporation_id,
        corporation_name=org.corporation_name,
        corporation_logo=corp_logo_url(org.corporation_id) if org.org_type == OrganisationType.CORPORATION.value else None,
        is_public=org.is_public, visibility=org.visibility or "private", following=following,
        created_at=org.created_at, my_role=role, member_count=count,
    )


# ---------------------------------------------------------------------------
# Organisation CRUD
# ---------------------------------------------------------------------------

@router.post("", response_model=OrganisationOut, status_code=status.HTTP_201_CREATED, responses={**ERR_400})
async def create_organisation(
        body: OrganisationCreate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    if db.query(Organisation).filter(Organisation.name == body.name).first():
        raise HTTPException(status_code=400, detail="Organisation name already taken")

    vis = (body.visibility.value if body.visibility
           else (PUBLIC if body.is_public else Visibility.PRIVATE.value))
    org = Organisation(
        name=body.name,
        owner_id=current_user.id,
        org_type=body.org_type.value,
        corporation_id=body.corporation_id,
        corporation_name=body.corporation_name,
        visibility=vis,
        is_public=(vis == PUBLIC),
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return _org_out(db, org, current_user.id)


@router.patch("/{org_id}", response_model=OrganisationOut, responses={**ERR_400, **ERR_403, **ERR_404})
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
    if body.visibility is not None:
        org.visibility = body.visibility.value
        org.is_public = (org.visibility == PUBLIC)
    elif body.is_public is not None:
        org.is_public = body.is_public
        org.visibility = PUBLIC if body.is_public else Visibility.PRIVATE.value

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


@router.get("/followed", response_model=List[OrganisationOut])
async def list_followed_organisations(
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Orgs the user follows (watch list) — distinct from joined membership."""
    ids = {r[0] for r in db.query(OrganisationFollow.org_id).filter(
        OrganisationFollow.user_id == current_user.id).all()}
    orgs = (db.query(Organisation).filter(Organisation.id.in_(ids)).order_by(Organisation.name).all()
            if ids else [])
    return [_org_out(db, o, current_user.id) for o in orgs]


@router.get("/lookup/corporation/{corporation_id}", responses={**ERR_404})
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


@router.get("/{org_id}", response_model=OrganisationOut, responses={**ERR_403, **ERR_404})
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


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT, responses={**ERR_403, **ERR_404})
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

@router.post("/{org_id}/join", response_model=OrganisationOut, responses={**ERR_400, **ERR_403, **ERR_404})
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


@router.delete("/{org_id}/leave", status_code=status.HTTP_204_NO_CONTENT, responses={**ERR_400, **ERR_404})
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


@router.post("/{org_id}/follow", response_model=OrganisationOut, responses={**ERR_400, **ERR_403, **ERR_404})
async def follow_organisation(
        org_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Add a public org to your watch list (lightweight — does NOT make you a member)."""
    org = _get_org_or_404(db, org_id)
    if not org.is_public:
        raise HTTPException(status_code=403, detail="This organisation is not public")
    if org.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="You own this organisation")
    exists = db.query(OrganisationFollow).filter(
        OrganisationFollow.org_id == org_id, OrganisationFollow.user_id == current_user.id).first()
    if not exists:
        db.add(OrganisationFollow(org_id=org_id, user_id=current_user.id))
        db.commit()
    return _org_out(db, org, current_user.id)


@router.delete("/{org_id}/follow", status_code=status.HTTP_204_NO_CONTENT, responses={**ERR_404})
async def unfollow_organisation(
        org_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    db.query(OrganisationFollow).filter(
        OrganisationFollow.org_id == org_id,
        OrganisationFollow.user_id == current_user.id,
    ).delete(synchronize_session=False)
    db.commit()


@router.get("/{org_id}/members", response_model=List[MemberOut], responses={**ERR_403, **ERR_404})
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


@router.patch("/{org_id}/members/{user_id}", response_model=MemberOut, responses={**ERR_403, **ERR_404})
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


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, responses={**ERR_403, **ERR_404})
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

@router.post("/{org_id}/employees", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED, responses={**ERR_400, **ERR_403, **ERR_404})
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


@router.get("/{org_id}/employees", response_model=List[EmployeeOut], responses={**ERR_403, **ERR_404})
async def list_org_employees(
        org_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_owner(org, current_user)
    return db.query(Employee).filter(Employee.organisation_id == org_id).all()


@router.patch("/{org_id}/employees/{emp_id}", response_model=EmployeeOut, responses={**ERR_400, **ERR_403, **ERR_404})
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

    emp.modified_at = utcnow()
    db.commit()
    db.refresh(emp)
    return emp


@router.delete("/{org_id}/employees/{emp_id}", status_code=status.HTTP_204_NO_CONTENT, responses={**ERR_403, **ERR_404})
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
    emp.deleted_at = utcnow()
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


@router.post("/me/characters", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED, tags=["characters"], responses={**ERR_400})
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


# ---------------------------------------------------------------------------
# Corporations: derived corp ↔ character link + per-corp tracking & roster
# ---------------------------------------------------------------------------

class CorpTrackingUpdate(BaseModel):
    tracked: bool


class RosterVisibilityUpdate(BaseModel):
    character_id: int
    visible: bool


@router.get("/me/corporations", tags=["corporations"])
async def my_corporations(
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """The corporations the user's linked characters belong to (derived from ESI
    affiliation), each with its character count, the matching corp-org id (if one exists)
    and the user's per-corp tracking toggle. Drives the Corporations page + tracking scope
    selector."""
    chars = (db.query(LinkedCharacter)
             .filter(LinkedCharacter.user_id == current_user.id,
                     LinkedCharacter.corporation_id.isnot(None)).all())
    by_corp: dict = {}
    for c in chars:
        d = by_corp.setdefault(c.corporation_id, {
            "corporation_id": c.corporation_id, "corporation_name": c.corporation_name,
            "character_count": 0})
        d["character_count"] += 1
        if not d["corporation_name"] and c.corporation_name:
            d["corporation_name"] = c.corporation_name

    org_by_corp = {o.corporation_id: o for o in db.query(Organisation).filter(
        Organisation.org_type == _CORP,
        Organisation.corporation_id.in_(list(by_corp) or [-1])).all()}
    untracked = {p.corporation_id for p in db.query(CorpTrackingPref).filter(
        CorpTrackingPref.user_id == current_user.id, CorpTrackingPref.tracked.is_(False)).all()}

    out = []
    for corp_id, d in by_corp.items():
        org = org_by_corp.get(corp_id)
        out.append({**d, "logo": corp_logo_url(corp_id),
                    "org_id": org.id if org else None,
                    "tracked": corp_id not in untracked})
    out.sort(key=lambda x: (x["corporation_name"] or "").lower())
    return out


@router.put("/me/corporations/{corporation_id}/tracking", tags=["corporations"])
async def set_corp_tracking(
        corporation_id: int,
        body: CorpTrackingUpdate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Toggle whether this corporation's characters feed the user's tracking. Off → they're
    dropped from the user's 'All characters' aggregate (see account_router._scoped_chars)."""
    pref = db.query(CorpTrackingPref).filter_by(
        user_id=current_user.id, corporation_id=corporation_id).first()
    if not pref:
        pref = CorpTrackingPref(user_id=current_user.id, corporation_id=corporation_id, created_at=utcnow())
        db.add(pref)
    pref.tracked = body.tracked
    pref.updated_at = utcnow()
    db.commit()
    return {"corporation_id": corporation_id, "tracked": body.tracked}


@router.get("/me/corporations/{corporation_id}/capital", tags=["corporations"])
async def corp_capital(
        corporation_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Liquid + assets capital of the requesting user's OWN characters in this corp (model
    R — never another user's wallet). Drives the corp dashboard Capital tab."""
    chars = (db.query(LinkedCharacter)
             .filter(LinkedCharacter.user_id == current_user.id,
                     LinkedCharacter.corporation_id == corporation_id).all())
    liquid = sum(c.wallet_balance or 0.0 for c in chars)
    assets = sum(c.assets_value or 0.0 for c in chars)
    return {
        "corporation_id": corporation_id,
        "character_count": len(chars),
        "liquid": round(liquid, 2), "assets": round(assets, 2), "total": round(liquid + assets, 2),
        "characters": [{"character_id": c.character_id, "character_name": c.character_name,
                        "wallet_balance": c.wallet_balance, "assets_value": c.assets_value,
                        "total": round((c.wallet_balance or 0.0) + (c.assets_value or 0.0), 2)}
                       for c in sorted(chars, key=lambda c: -((c.wallet_balance or 0) + (c.assets_value or 0)))],
    }


@router.post("/me/corporations/{corporation_id}/org", response_model=OrganisationOut,
             status_code=status.HTTP_201_CREATED, tags=["corporations"], responses={**ERR_400, **ERR_404})
async def create_corp_org(
        corporation_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """One-click create + link a Corporation-type Organisation for one of the user's
    corporations, so it becomes usable in the org → projects flow (and the corp dashboard's
    Members/Projects). Guards: the user must have a linked character in that corp; only one
    corp-org per (owner, corporation) — if it already exists, the existing one is returned."""
    char = (db.query(LinkedCharacter)
            .filter(LinkedCharacter.user_id == current_user.id,
                    LinkedCharacter.corporation_id == corporation_id).first())
    if not char:
        raise HTTPException(status_code=404, detail="You have no linked character in that corporation")

    existing = (db.query(Organisation)
                .filter(Organisation.owner_id == current_user.id,
                        Organisation.org_type == _CORP,
                        Organisation.corporation_id == corporation_id).first())
    if existing:                                   # idempotent — reuse the user's corp-org
        return _org_out(db, existing, current_user.id)

    corp_name = char.corporation_name
    if not corp_name:
        try:
            corp_name = esi.fetch_corporation(corporation_id).get("name")
        except Exception:  # noqa: BLE001
            corp_name = None
    corp_name = corp_name or f"Corp {corporation_id}"

    # Organisation.name is globally unique — disambiguate on clash with the corp id
    name = corp_name
    if db.query(Organisation).filter(Organisation.name == name).first():
        name = f"{corp_name} [{corporation_id}]"
        if db.query(Organisation).filter(Organisation.name == name).first():
            raise HTTPException(status_code=400, detail="An organisation with this name already exists")

    org = Organisation(
        name=name, owner_id=current_user.id, org_type=_CORP,
        corporation_id=corporation_id, corporation_name=corp_name,
        visibility=Visibility.PRIVATE.value, is_public=False,
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return _org_out(db, org, current_user.id)


@router.get("/me/corporations/{corporation_id}/corp-data", tags=["corporations"], responses={**ERR_404})
async def corp_data(
        corporation_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Real corp-level data (Phase B): the corporation's OWN wallet, industry jobs and member
    roster — not a regrouping of the user's personal characters. Returns ``access`` flags so the
    UI can prompt for a director to grant corp-ESI when data isn't available (and avoid showing
    personal work as corp work). Also returns the user's own-character capital in this corp as a
    clearly-separated ``personal`` block."""
    my_chars = (db.query(LinkedCharacter)
                .filter(LinkedCharacter.user_id == current_user.id,
                        LinkedCharacter.corporation_id == corporation_id).all())
    if not my_chars:
        raise HTTPException(status_code=404, detail="You have no linked character in that corporation")

    roles = sorted({r for c in my_chars for r in (c.corp_roles or [])})
    can_wallet = any(_char_has_scope(c, _SC_CORP_WALLET) and (set(c.corp_roles or []) & _R_ACCOUNTANT) for c in my_chars)
    can_jobs = any(_char_has_scope(c, _SC_CORP_JOBS) and (set(c.corp_roles or []) & _R_FACTORY) for c in my_chars)
    can_members = any(_char_has_scope(c, _SC_CORP_MEMBERS) for c in my_chars)
    need_relink = not any(_char_has_scope(c, s) for c in my_chars
                          for s in (_SC_CORP_WALLET, _SC_CORP_JOBS, _SC_CORP_MEMBERS))

    # wallet (corp-wide, real)
    wrows = db.query(EsiCorpWallet).filter(EsiCorpWallet.corporation_id == corporation_id).all()
    wallet = None
    if wrows:
        synced = max((w.synced_at for w in wrows if w.synced_at), default=None)
        wallet = {
            "total": round(sum(w.balance or 0.0 for w in wrows), 2),
            "divisions": [{"division": w.division, "balance": w.balance}
                          for w in sorted(wrows, key=lambda w: w.division)],
            "synced_at": synced.isoformat() if synced else None,
        }

    # industry jobs (corp-OWNED, real)
    jrows = (db.query(EsiCorpIndustryJob)
             .filter(EsiCorpIndustryJob.corporation_id == corporation_id)
             .order_by(EsiCorpIndustryJob.end_date.desc()).limit(300).all())
    jobs = None
    if jrows or can_jobs:
        prod_ids = {j.product_type_id for j in jrows if j.product_type_id}
        installer_ids = {j.installer_id for j in jrows if j.installer_id}
        names: dict = {}
        if prod_ids:
            eve = EveSessionLocal()
            try:
                names = dict(eve.query(EveType.type_id, EveType.type_name)
                             .filter(EveType.type_id.in_(prod_ids)).all())
            finally:
                eve.close()
        inst_names = {cid: nm for cid, nm in
                      db.query(EsiCorpMember.character_id, EsiCorpMember.character_name)
                      .filter(EsiCorpMember.corporation_id == corporation_id,
                              EsiCorpMember.character_id.in_(installer_ids or [-1])).all()}
        jobs = {
            "active": sum(1 for j in jrows if j.status in _CORP_JOB_ACTIVE),
            "total": len(jrows),
            "rows": [{
                "job_id": j.job_id,
                "installer": inst_names.get(j.installer_id) or (f"#{j.installer_id}" if j.installer_id else "—"),
                "activity": _CORP_ACT.get(j.activity_id, "Other"),
                "product_name": names.get(j.product_type_id) or (f"Type #{j.product_type_id}" if j.product_type_id else "—"),
                "runs": j.runs, "status": j.status,
                "end_date": j.end_date.isoformat() if j.end_date else None,
                "cost": j.cost,
            } for j in jrows],
        }

    # members (real in-game roster)
    mrows = db.query(EsiCorpMember).filter(EsiCorpMember.corporation_id == corporation_id).all()
    my_ids = {c.character_id for c in my_chars}
    members = None
    if mrows or can_members:
        members = {
            "count": len(mrows),
            "rows": [{"character_id": m.character_id,
                      "character_name": m.character_name or f"#{m.character_id}",
                      "is_mine": m.character_id in my_ids}
                     for m in sorted(mrows, key=lambda m: (m.character_name or "~").lower())][:1000],
        }

    # the user's own characters' capital in this corp — kept SEPARATE from the corp wallet so
    # personal funds are never presented as the corporation's.
    liquid = sum(c.wallet_balance or 0.0 for c in my_chars)
    assets = sum(c.assets_value or 0.0 for c in my_chars)
    personal = {"character_count": len(my_chars), "liquid": round(liquid, 2),
                "assets": round(assets, 2), "total": round(liquid + assets, 2)}

    return {
        "corporation_id": corporation_id,
        "access": {"roles": roles, "can_wallet": can_wallet, "can_jobs": can_jobs,
                   "can_members": can_members, "need_relink": need_relink},
        "wallet": wallet, "jobs": jobs, "members": members, "personal": personal,
    }


@router.put("/me/corp-roster-visibility", tags=["corporations"], responses={**ERR_404})
async def set_corp_roster_visibility(
        body: RosterVisibilityUpdate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Opt one of the user's own characters in/out of its corp's activity roster (presence
    only — never financial). Off by default."""
    ch = db.query(LinkedCharacter).filter_by(
        character_id=body.character_id, user_id=current_user.id).first()
    if not ch:
        raise HTTPException(status_code=404, detail="Character not found")
    ch.corp_roster_visible = body.visible
    db.commit()
    return {"character_id": body.character_id, "visible": body.visible}


@router.get("/{org_id}/corp/members", tags=["corporations"], responses={**ERR_400, **ERR_403, **ERR_404})
async def corp_roster(
        org_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Activity roster for a corp-org: every character (across all app users) IN this
    corporation that has opted into roster visibility — presence only (online / last login /
    last sync / location / ship), NO financial fields. Role-gated to SENIOR+ so juniors can't
    enumerate the corp."""
    org = _get_org_or_404(db, org_id)
    if org.org_type != _CORP or not org.corporation_id:
        raise HTTPException(status_code=400, detail="Not a corporation organisation")
    _require_write(db, org, current_user)

    chars = (db.query(LinkedCharacter)
             .filter(LinkedCharacter.corporation_id == org.corporation_id,
                     LinkedCharacter.corp_roster_visible.is_(True)).all())
    sys_ids = {c.location_system_id for c in chars if c.location_system_id}
    st_ids = {c.location_id for c in chars if c.location_id and c.location_type == "station"}
    eve = EveSessionLocal()
    try:
        sysnames = dict(eve.query(EveSolarSystem.solar_system_id, EveSolarSystem.solar_system_name)
                        .filter(EveSolarSystem.solar_system_id.in_(sys_ids or [-1])).all())
        stnames = dict(eve.query(EveStation.station_id, EveStation.station_name)
                       .filter(EveStation.station_id.in_(st_ids or [-1])).all())
    finally:
        eve.close()

    members = [{
        "character_id": c.character_id,
        "character_name": c.character_name,
        "online": c.online,
        "last_login": c.last_login.isoformat() if c.last_login else None,
        "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
        "system": sysnames.get(c.location_system_id),
        "station": stnames.get(c.location_id) if c.location_type == "station" else None,
        "ship_name": c.ship_name,
    } for c in sorted(chars, key=lambda c: (not c.online, c.character_name or ""))]
    return {"members": members, "corporation_id": org.corporation_id}
