import datetime
from app.core.config import SQLALCHEMY_DATABASE_URL
from sqlalchemy import (
    create_engine, Column, Integer, Enum,
    ForeignKey, String, DateTime, Boolean, Float, Text, BigInteger,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from app.core.schemas import EmployeeType, ProjectsType, ProjectsStatus


engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class UserDB(Base):
    __tablename__ = "users"

    id                  = Column(Integer, primary_key=True, index=True)
    username            = Column(String, unique=True, index=True, nullable=False)
    hashed_password     = Column(String, nullable=False)
    email               = Column(String, nullable=False, unique=True, index=True)

    main_character      = Column(String, nullable=True, unique=True, index=True)
    main_character_id   = Column(Integer, nullable=True)
    corporation         = Column(String, nullable=True)
    corporation_id      = Column(Integer, nullable=True)
    alliance            = Column(String, nullable=True)
    alliance_id         = Column(Integer, nullable=True)

    organisations       = relationship("Organisation", back_populates="owner_user")
    characters          = relationship("Employee", back_populates="owner_user")


class Organisation(Base):
    __tablename__ = "organisations"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String, unique=True, index=True, nullable=False)
    owner_id   = Column(Integer, ForeignKey("users.id"), nullable=False)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    owner_user = relationship("UserDB", back_populates="organisations")
    employees  = relationship("Employee", back_populates="organisation")
    projects   = relationship("Projects", back_populates="organisation")


class Employee(Base):
    __tablename__ = "employees"

    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(String, unique=True, index=True, nullable=False)  # character name
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=False)
    character_id    = Column(Integer, nullable=True)   # EVE character ID from ESI
    organisation_id = Column(Integer, ForeignKey("organisations.id"), nullable=True)

    status     = Column(Enum(EmployeeType), nullable=False, index=True, default=EmployeeType.OTHER)

    added_at    = Column(DateTime, default=datetime.datetime.utcnow)
    modified_at = Column(DateTime, nullable=True)
    deleted_at  = Column(DateTime, nullable=True)

    owner_user   = relationship("UserDB", back_populates="characters")
    organisation = relationship("Organisation", back_populates="employees")

    created_projects   = relationship("Projects", foreign_keys="Projects.created_by",   back_populates="creator")
    supervised_projects= relationship("Projects", foreign_keys="Projects.supervised_by", back_populates="supervisor")


class Projects(Base):
    __tablename__ = "projects"

    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(String, unique=True, index=True, nullable=False)
    created_by      = Column(Integer, ForeignKey("employees.id"), nullable=False)
    supervised_by   = Column(Integer, ForeignKey("employees.id"), nullable=True)
    organisation_id = Column(Integer, ForeignKey("organisations.id"), nullable=False)

    org_project_code = Column(String, nullable=True, index=True)
    note             = Column(String, nullable=True)
    project_type     = Column(Enum(ProjectsType), nullable=False, index=True)
    status           = Column(Enum(ProjectsStatus), nullable=False, index=True, default=ProjectsStatus.ACTIVE)
    repeatable       = Column(Boolean, nullable=False, default=False)

    created_at  = Column(DateTime, default=datetime.datetime.utcnow)
    modified_at = Column(DateTime, nullable=True)
    deadline_at = Column(DateTime, nullable=True)
    deleted_at  = Column(DateTime, nullable=True)

    organisation = relationship("Organisation", back_populates="projects")
    creator      = relationship("Employee", foreign_keys=[created_by],   back_populates="created_projects")
    supervisor   = relationship("Employee", foreign_keys=[supervised_by], back_populates="supervised_projects")


class InventoryItem(Base):
    __tablename__ = "inventory"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id  = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)

    eve_type_id = Column(Integer, nullable=True, index=True)   # resolved from eve_types
    name        = Column(String(200), nullable=False)
    volume      = Column(Float, nullable=True)                  # m³ per unit, from SDE
    quantity    = Column(BigInteger, nullable=False, default=1)
    price       = Column(Float, nullable=True)                  # ISK per unit
    place       = Column(String(200), nullable=True)            # solar system / station name
    note        = Column(Text, nullable=True)

    created_at  = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at  = Column(DateTime, nullable=True)

    owner       = relationship("UserDB", backref="inventory")
    project     = relationship("Projects", backref="inventory")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


Base.metadata.create_all(bind=engine)