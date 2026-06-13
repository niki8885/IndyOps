import datetime
from app.core.config import SQLALCHEMY_DATABASE_URL
from sqlalchemy import (
    create_engine, Column, Integer, Enum,
    ForeignKey, String, DateTime, Boolean, Float, Text, BigInteger, JSON,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from app.core.schemas import (
    EmployeeType, ProjectsType, ProjectsStatus,
    FacilityType, ProductionStatus, ProductionTarget,
)


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


class Facility(Base):
    """Player-owned manufacturing facilities (Raitaru, Azbel, Sotiyo, etc.)."""
    __tablename__ = "facilities"

    id                = Column(Integer, primary_key=True, index=True)
    user_id           = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    name              = Column(String(200), nullable=False)
    facility_type     = Column(Enum(FacilityType), nullable=False, index=True)

    tax               = Column(Float, nullable=True)   # broker/facility tax %
    cost_bonus        = Column(Float, nullable=True)   # material/time cost reduction %

    system_name       = Column(String(200), nullable=True, index=True)
    system_cost_index = Column(Float, nullable=True)   # ESI manufacturing cost index

    # Rigs — stored as (eve_type_id, display name) pairs
    rig1_type_id      = Column(Integer, nullable=True)
    rig1_name         = Column(String(200), nullable=True)
    rig2_type_id      = Column(Integer, nullable=True)
    rig2_name         = Column(String(200), nullable=True)
    rig3_type_id      = Column(Integer, nullable=True)
    rig3_name         = Column(String(200), nullable=True)

    created_at        = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at        = Column(DateTime, nullable=True)

    owner = relationship("UserDB", backref="facilities")


class ProductionJob(Base):
    """PAK — a manufacturing production job/contract."""
    __tablename__ = "production_jobs"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id  = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id"), nullable=True)

    # Blueprint / product
    blueprint_type_id = Column(Integer, nullable=True)
    blueprint_name    = Column(String(200), nullable=True)
    product_type_id   = Column(Integer, nullable=False)
    product_name      = Column(String(200), nullable=False)

    # Production parameters
    runs    = Column(Integer, nullable=False, default=1)
    me      = Column(Integer, nullable=False, default=0)   # 0-10
    te      = Column(Integer, nullable=False, default=0)   # 0-20
    bpc_cost = Column(Float, nullable=True, default=0)

    # PAK contract metadata
    paks          = Column(Integer, nullable=True)
    units_per_pak = Column(Integer, nullable=True)
    pack_tier     = Column(String(10), nullable=True)      # F, E, D …
    pak_reward    = Column(Float, nullable=True)           # ISK paid to producer

    # Pricing snapshot
    sell_price  = Column(Float, nullable=True)
    jita_sell   = Column(Float, nullable=True)
    jita_buy    = Column(Float, nullable=True)
    cj_sell     = Column(Float, nullable=True)
    cj_buy      = Column(Float, nullable=True)
    initial_contract_price = Column(Float, nullable=True)
    return_contract_price  = Column(Float, nullable=True)

    # Last calculation result stored as JSON
    calc_snapshot = Column(JSON, nullable=True)

    # Status / tracking
    status  = Column(Enum(ProductionStatus), nullable=False, default=ProductionStatus.PLANNING, index=True)
    target  = Column(Enum(ProductionTarget), nullable=True)
    place   = Column(String(200), nullable=True)

    date_planned  = Column(DateTime, default=datetime.datetime.utcnow)
    date_released = Column(DateTime, nullable=True)

    # Codes
    code          = Column(String(100), nullable=True)
    contract_code = Column(String(500), nullable=True)
    note          = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    owner    = relationship("UserDB", backref="production_jobs")
    project  = relationship("Projects", backref="production_jobs")
    facility = relationship("Facility", backref="production_jobs")


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