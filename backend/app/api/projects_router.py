import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db, Projects, Organisation, Employee, UserDB
from app.core.schemas import ProjectsType, ProjectsStatus
from app.core.security import get_current_user

router = APIRouter()

class ProjectCreate(BaseModel):
    name: str
    project_type: ProjectsType
    created_by: int
    supervised_by: Optional[int] = None
    org_project_code: Optional[str] = None
    note: Optional[str] = None
    repeatable: bool = False
    deadline_at: Optional[datetime.datetime] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    project_type: Optional[ProjectsType] = None
    status: Optional[ProjectsStatus] = None
    supervised_by: Optional[int] = None
    org_project_code: Optional[str] = None
    note: Optional[str] = None
    repeatable: Optional[bool] = None
    deadline_at: Optional[datetime.datetime] = None

class ProjectOut(BaseModel):
    id: int
    name: str
    organisation_id: int
    created_by: int
    supervised_by: Optional[int]
    project_type: ProjectsType
    status: ProjectsStatus
    org_project_code: Optional[str]
    note: Optional[str]
    repeatable: bool
    created_at: datetime.datetime
    modified_at: Optional[datetime.datetime]
    deadline_at: Optional[datetime.datetime]

    class Config:
        from_attributes = True

@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    org_id: int,
    body: ProjectCreate,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_owner(org, current_user)

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
        deadline_at=body.deadline_at,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=List[ProjectOut])
async def list_projects(
    org_id: int,
    project_type: Optional[ProjectsType]   = None,
    proj_status:  Optional[ProjectsStatus] = None,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_owner(org, current_user)

    q = db.query(Projects).filter(
        Projects.organisation_id == org_id,
        Projects.deleted_at == None,
    )
    if project_type:
        q = q.filter(Projects.project_type == project_type)
    if proj_status:
        q = q.filter(Projects.status == proj_status)
    return q.all()


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    org_id: int,
    project_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_owner(org, current_user)
    return _get_project_or_404(db, project_id, org_id)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    org_id: int,
    project_id: int,
    body: ProjectUpdate,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_owner(org, current_user)
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
    if body.deadline_at is not None: project.deadline_at = body.deadline_at

    if body.supervised_by is not None:
        supervisor = _get_emp_or_404(db, body.supervised_by)
        if supervisor.organisation_id != org_id:
            raise HTTPException(status_code=400, detail="Supervisor is not in this organisation")
        project.supervised_by = body.supervised_by

    project.modified_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    org_id: int,
    project_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = _get_org_or_404(db, org_id)
    _require_owner(org, current_user)
    project = _get_project_or_404(db, project_id, org_id)

    project.status = ProjectsStatus.DELETED
    project.deleted_at = datetime.datetime.utcnow()
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