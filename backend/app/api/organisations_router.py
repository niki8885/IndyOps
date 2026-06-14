import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db, Organisation, Employee, UserDB
from app.core.schemas import EmployeeType, OrganisationType
from app.core.security import get_current_user

router = APIRouter()


class OrganisationCreate(BaseModel):
    name: str
    org_type: OrganisationType = OrganisationType.PERSONAL
    corporation_id: Optional[int] = None
    corporation_name: Optional[str] = None


class OrganisationUpdate(BaseModel):
    name: Optional[str] = None
    org_type: Optional[OrganisationType] = None
    corporation_id: Optional[int] = None
    corporation_name: Optional[str] = None


class OrganisationOut(BaseModel):
    id: int
    name: str
    owner_id: int
    org_type: Optional[str] = None
    corporation_id: Optional[int] = None
    corporation_name: Optional[str] = None
    created_at: datetime.datetime

    class Config:
        from_attributes = True


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
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


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

    db.commit()
    db.refresh(org)
    return org


@router.get("", response_model=List[OrganisationOut])
async def list_my_organisations(
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    return db.query(Organisation).filter(Organisation.owner_id == current_user.id).all()


@router.get("/{org_id}", response_model=OrganisationOut)
async def get_organisation(
        org_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_owner(org, current_user)
    return org


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
