import datetime
from app.core.timeutil import utcnow
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db, Projects, Organisation, OrganisationMember, Employee, UserDB
from app.core.schemas import ProjectsType, ProjectsStatus, ProjectPriority
from app.core.security import get_current_user
from app.api.responses import ERR_400, ERR_403, ERR_404

_WRITE_ROLES = {"OWNER", "ADMIN", "SENIOR"}

router = APIRouter()


class ProjectCreate(BaseModel):
    name: str
    project_type: ProjectsType
    created_by: int
    supervised_by: Optional[int] = None
    org_project_code: Optional[str] = None
    note: Optional[str] = None
    repeatable: bool = False
    closed: bool = False
    priority: ProjectPriority = ProjectPriority.MEDIUM
    deadline_at: Optional[datetime.datetime] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    project_type: Optional[ProjectsType] = None
    status: Optional[ProjectsStatus] = None
    supervised_by: Optional[int] = None
    org_project_code: Optional[str] = None
    note: Optional[str] = None
    repeatable: Optional[bool] = None
    closed: Optional[bool] = None
    priority: Optional[ProjectPriority] = None
    deadline_at: Optional[datetime.datetime] = None


class ProjectOut(BaseModel):
    id: int
    name: str
    organisation_id: int
    created_by: int
    supervised_by: Optional[int] = None
    project_type: ProjectsType
    status: ProjectsStatus
    org_project_code: Optional[str] = None
    note: Optional[str] = None
    repeatable: bool
    closed: Optional[bool] = False
    priority: Optional[str] = "medium"
    created_at: datetime.datetime
    modified_at: Optional[datetime.datetime] = None
    deadline_at: Optional[datetime.datetime] = None
    class Config:
        from_attributes = True


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED, responses={**ERR_400, **ERR_403, **ERR_404})
async def create_project(
        org_id: int,
        body: ProjectCreate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_write_access(db, org, current_user)

    creator = _get_emp_or_404(db, body.created_by)
    if creator.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Creator character does not belong to you")

    if body.supervised_by:
        supervisor = _get_emp_or_404(db, body.supervised_by)
        if supervisor.organisation_id != org_id:
            raise HTTPException(status_code=400, detail="Supervisor is not in this organisation")

    if db.query(Projects).filter(Projects.name == body.name).first():
        raise HTTPException(status_code=400, detail="Project name already exists")

    project = Projects(
        name=body.name,
        organisation_id=org_id,
        created_by=body.created_by,
        supervised_by=body.supervised_by,
        project_type=body.project_type,
        status=ProjectsStatus.ACTIVE,
        org_project_code=body.org_project_code,
        note=body.note,
        repeatable=body.repeatable,
        closed=body.closed,
        priority=body.priority.value,
        deadline_at=body.deadline_at,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=List[ProjectOut], responses={**ERR_403, **ERR_404})
async def list_projects(
        org_id: int,
        project_type: Optional[ProjectsType] = None,
        proj_status: Optional[ProjectsStatus] = None,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_read_access(db, org, current_user)

    q = db.query(Projects).filter(
        Projects.organisation_id == org_id,
        Projects.deleted_at == None,
    )
    if project_type:
        q = q.filter(Projects.project_type == project_type)
    if proj_status:
        q = q.filter(Projects.status == proj_status)
    return q.all()


@router.get("/{project_id}", response_model=ProjectOut, responses={**ERR_403, **ERR_404})
async def get_project(
        org_id: int,
        project_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_read_access(db, org, current_user)
    return _get_project_or_404(db, project_id, org_id)


@router.patch("/{project_id}", response_model=ProjectOut, responses={**ERR_400, **ERR_403, **ERR_404})
async def update_project(
        org_id: int,
        project_id: int,
        body: ProjectUpdate,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_write_access(db, org, current_user)
    project = _get_project_or_404(db, project_id, org_id)

    if body.name is not None:
        existing = db.query(Projects).filter(Projects.name == body.name, Projects.id != project_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Project name already taken")
        project.name = body.name

    if body.project_type is not None: project.project_type = body.project_type
    if body.status is not None: project.status = body.status
    if body.org_project_code is not None: project.org_project_code = body.org_project_code
    if body.note is not None: project.note = body.note
    if body.repeatable is not None: project.repeatable = body.repeatable
    if body.closed is not None: project.closed = body.closed
    if body.priority is not None: project.priority = body.priority.value
    if body.deadline_at is not None: project.deadline_at = body.deadline_at

    if body.supervised_by is not None:
        supervisor = _get_emp_or_404(db, body.supervised_by)
        if supervisor.organisation_id != org_id:
            raise HTTPException(status_code=400, detail="Supervisor is not in this organisation")
        project.supervised_by = body.supervised_by

    project.modified_at = utcnow()
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, responses={**ERR_403, **ERR_404})
async def delete_project(
        org_id: int,
        project_id: int,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_write_access(db, org, current_user)
    project = _get_project_or_404(db, project_id, org_id)

    project.status = ProjectsStatus.DELETED
    project.deleted_at = utcnow()
    db.commit()


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


def _get_project_or_404(db: Session, project_id: int, org_id: int) -> Projects:
    project = db.query(Projects).filter(
        Projects.id == project_id,
        Projects.organisation_id == org_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _require_owner(org: Organisation, user: UserDB):
    if org.owner_id != user.id:
        raise HTTPException(status_code=403, detail="You are not the owner of this organisation")


def _member_role(db: Session, org: Organisation, user_id: int) -> Optional[str]:
    if org.owner_id == user_id:
        return "OWNER"
    m = db.query(OrganisationMember).filter(
        OrganisationMember.org_id == org.id,
        OrganisationMember.user_id == user_id,
    ).first()
    return m.role if m else None


def _require_read_access(db: Session, org: Organisation, user: UserDB):
    """Any member (any role) can read. Non-members are denied."""
    if _member_role(db, org, user.id) is None:
        raise HTTPException(status_code=403, detail="You are not a member of this organisation")


def _require_write_access(db: Session, org: Organisation, user: UserDB):
    """SENIOR and above can write (create/update/delete)."""
    role = _member_role(db, org, user.id)
    if role not in _WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient role — SENIOR or above required")
