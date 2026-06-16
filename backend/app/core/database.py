import datetime
import os
from app.core.config import SQLALCHEMY_DATABASE_URL
from sqlalchemy import (
    create_engine, Column, Integer, Enum,
    ForeignKey, String, DateTime, Boolean, Float, Text, BigInteger, JSON,
    Index, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from app.core.schemas import (
    EmployeeType, ProjectsType, ProjectsStatus,
    FacilityType, ProductionStatus, ProductionTarget, OrganisationType,
)
from sqlalchemy import text

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True, index=True)

    main_character = Column(String, nullable=True, unique=True, index=True)
    main_character_id = Column(Integer, nullable=True)
    corporation = Column(String, nullable=True)
    corporation_id = Column(Integer, nullable=True)
    alliance = Column(String, nullable=True)
    alliance_id = Column(Integer, nullable=True)

    organisations = relationship("Organisation", back_populates="owner_user")
    characters = relationship("Employee", back_populates="owner_user")


class Organisation(Base):
    __tablename__ = "organisations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    org_type = Column(String(20), nullable=False, default=OrganisationType.PERSONAL.value)
    corporation_id = Column(Integer, nullable=True)  # real in-game corp ID
    corporation_name = Column(String(200), nullable=True)
    is_public = Column(Boolean, nullable=False, default=False, server_default="false")

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    owner_user = relationship("UserDB", back_populates="organisations")
    employees = relationship("Employee", back_populates="organisation")
    projects = relationship("Projects", back_populates="organisation")
    members = relationship("OrganisationMember", back_populates="organisation", cascade="all, delete-orphan")


class OrganisationMember(Base):
    """Links an IndyOps user to an org they have joined (distinct from EVE characters / employees)."""
    __tablename__ = "organisation_members"
    __table_args__ = (UniqueConstraint("org_id", "user_id"),)

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False, default="JUNIOR")
    joined_at = Column(DateTime, default=datetime.datetime.utcnow)

    organisation = relationship("Organisation", back_populates="members")
    member_user = relationship("UserDB")


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)  # character name
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    character_id = Column(Integer, nullable=True)  # EVE character ID from ESI
    organisation_id = Column(Integer, ForeignKey("organisations.id"), nullable=True)

    status = Column(Enum(EmployeeType), nullable=False, index=True, default=EmployeeType.OTHER)

    added_at = Column(DateTime, default=datetime.datetime.utcnow)
    modified_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)

    owner_user = relationship("UserDB", back_populates="characters")
    organisation = relationship("Organisation", back_populates="employees")

    created_projects = relationship("Projects", foreign_keys="Projects.created_by", back_populates="creator")
    supervised_projects = relationship("Projects", foreign_keys="Projects.supervised_by", back_populates="supervisor")


class Projects(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    created_by = Column(Integer, ForeignKey("employees.id"), nullable=False)
    supervised_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    organisation_id = Column(Integer, ForeignKey("organisations.id"), nullable=False)

    org_project_code = Column(String, nullable=True, index=True)
    note = Column(String, nullable=True)
    project_type = Column(Enum(ProjectsType), nullable=False, index=True)
    status = Column(Enum(ProjectsStatus), nullable=False, index=True, default=ProjectsStatus.ACTIVE)
    repeatable = Column(Boolean, nullable=False, default=False)
    closed = Column(Boolean, nullable=False, default=False)
    priority = Column(String(10), nullable=False, default="medium")

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    modified_at = Column(DateTime, nullable=True)
    deadline_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)

    organisation = relationship("Organisation", back_populates="projects")
    creator = relationship("Employee", foreign_keys=[created_by], back_populates="created_projects")
    supervisor = relationship("Employee", foreign_keys=[supervised_by], back_populates="supervised_projects")


class Facility(Base):
    """Player-owned manufacturing facilities (Raitaru, Azbel, Sotiyo, etc.)."""
    __tablename__ = "facilities"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    organisation_id = Column(Integer, ForeignKey("organisations.id"), nullable=True, index=True)

    name = Column(String(200), nullable=False)
    facility_type = Column(Enum(FacilityType), nullable=False, index=True)

    tax = Column(Float, nullable=True)  # broker/facility tax %
    cost_bonus = Column(Float, nullable=True)  # material/time cost reduction %

    system_name = Column(String(200), nullable=True, index=True)
    system_cost_index = Column(Float, nullable=True)  # ESI manufacturing cost index

    # Rigs — stored as (eve_type_id, display name) pairs
    rig1_type_id = Column(Integer, nullable=True)
    rig1_name = Column(String(200), nullable=True)
    rig2_type_id = Column(Integer, nullable=True)
    rig2_name = Column(String(200), nullable=True)
    rig3_type_id = Column(Integer, nullable=True)
    rig3_name = Column(String(200), nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    owner = relationship("UserDB", backref="facilities")


class Blueprint(Base):
    """A blueprint the user owns — BPO (original, unlimited runs) or BPC (copy, with
    a run count and a purchase cost). The chain uses its ME/TE for the product it
    makes and folds a BPC's cost into the build."""
    __tablename__ = "blueprints"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    organisation_id = Column(Integer, ForeignKey("organisations.id"), nullable=True, index=True)

    blueprint_type_id = Column(Integer, nullable=False, index=True)
    product_type_id = Column(Integer, nullable=False, index=True)   # what it makes — chain join key
    name = Column(String(200), nullable=False)

    is_bpo = Column(Boolean, nullable=False, default=True)
    me = Column(Integer, nullable=False, default=0)
    te = Column(Integer, nullable=False, default=0)
    runs = Column(Integer, nullable=True)        # remaining runs for a BPC; null = BPO / unlimited
    quantity = Column(Integer, nullable=False, default=1)
    cost = Column(Float, nullable=True)          # purchase cost per copy (BPC)
    facility_id = Column(Integer, ForeignKey("facilities.id"), nullable=True)
    note = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    owner = relationship("UserDB", backref="blueprints")


class ProductionJob(Base):
    """PAK — a manufacturing production job/contract."""
    __tablename__ = "production_jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id"), nullable=True)

    # Blueprint / product
    blueprint_type_id = Column(Integer, nullable=True)
    blueprint_name = Column(String(200), nullable=True)
    product_type_id = Column(Integer, nullable=False)
    product_name = Column(String(200), nullable=False)

    # Production parameters
    runs = Column(Integer, nullable=False, default=1)
    windows = Column(Integer, nullable=False, default=1)  # parallel production slots
    me = Column(Integer, nullable=False, default=0)  # 0-10
    te = Column(Integer, nullable=False, default=0)  # 0-20
    bpc_cost = Column(Float, nullable=True, default=0)

    # PAK contract metadata
    paks = Column(Integer, nullable=True)
    units_per_pak = Column(Integer, nullable=True)
    pack_tier = Column(String(10), nullable=True)  # F, E, D …
    pak_reward = Column(Float, nullable=True)  # ISK paid to producer

    # Pricing snapshot
    sell_price = Column(Float, nullable=True)
    jita_sell = Column(Float, nullable=True)
    jita_buy = Column(Float, nullable=True)
    cj_sell = Column(Float, nullable=True)
    cj_buy = Column(Float, nullable=True)
    initial_contract_price = Column(Float, nullable=True)
    return_contract_price = Column(Float, nullable=True)

    # Last calculation result stored as JSON
    calc_snapshot = Column(JSON, nullable=True)

    # Status / tracking
    status = Column(Enum(ProductionStatus), nullable=False, default=ProductionStatus.PLANNING, index=True)
    target = Column(Enum(ProductionTarget), nullable=True)
    place = Column(String(200), nullable=True)

    date_planned = Column(DateTime, default=datetime.datetime.utcnow)
    date_released = Column(DateTime, nullable=True)

    # Codes
    code = Column(String(100), nullable=True)
    contract_code = Column(String(500), nullable=True)
    note = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    owner = relationship("UserDB", backref="production_jobs")
    project = relationship("Projects", backref="production_jobs")
    facility = relationship("Facility", backref="production_jobs")


class InventoryItem(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)

    eve_type_id = Column(Integer, nullable=True, index=True)  # resolved from eve_types
    name = Column(String(200), nullable=False)
    volume = Column(Float, nullable=True)  # m³ per unit, from SDE
    quantity = Column(BigInteger, nullable=False, default=1)
    price = Column(Float, nullable=True)  # ISK per unit (cost basis)
    place = Column(String(200), nullable=True)  # solar system / station name
    note = Column(Text, nullable=True)

    flow = Column(String(10), nullable=False, default="input")  # input | output
    item_status = Column(String(12), nullable=False, default="in_stock")  # in_stock | used | sold
    sale_price = Column(Float, nullable=True)  # ISK per unit when sold

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    owner = relationship("UserDB", backref="inventory")
    project = relationship("Projects", backref="inventory")


class StockMovement(Base):
    """Audit log of warehouse stock changes (e.g. materials consumed by a PAK job)."""
    __tablename__ = "stock_movements"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    production_job_id = Column(Integer, ForeignKey("production_jobs.id"), nullable=True, index=True)

    eve_type_id = Column(Integer, nullable=True, index=True)
    name = Column(String(200), nullable=False)
    quantity = Column(BigInteger, nullable=False)  # absolute amount moved
    direction = Column(String(8), nullable=False, default="out")  # 'out' = consumed, 'in' = added
    unit_cost = Column(Float, nullable=True)
    total_cost = Column(Float, nullable=True)
    reason = Column(String(200), nullable=True)  # e.g. "PAK #12 issue"
    note = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    owner = relationship("UserDB", backref="stock_movements")
    project = relationship("Projects", backref="stock_movements")
    job = relationship("ProductionJob", backref="stock_movements")


class TrackedPlace(Base):
    """A user's favourite system/region for price tracking."""
    __tablename__ = "tracked_places"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String(10), nullable=False)  # system | region
    name = Column(String(200), nullable=False)
    region_id = Column(Integer, nullable=True)  # used for Fuzzwork fetch
    solar_system_id = Column(Integer, nullable=True)
    special_parser = Column(Boolean, nullable=False, default=False)  # C-J → appraise.gnf.lt
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class TrackedItem(Base):
    """A user's tracked item + which favourite places to track it in."""
    __tablename__ = "tracked_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type_id = Column(Integer, nullable=False)
    name = Column(String(200), nullable=False)
    place_ids = Column(JSON, nullable=True)  # [tracked_place_id, …]
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class TrackPrice(Base):
    """Hourly buy/sell/volume snapshot for a tracked (item, place)."""
    __tablename__ = "track_prices"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type_id = Column(Integer, nullable=False)
    place_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    buy = Column(Float, nullable=True)
    sell = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)

    # one composite index serves the (type_id[, place_id[, timestamp]]) read path,
    # replacing the three separate single-column indexes.
    __table_args__ = (
        Index("ix_track_prices_type_place_ts", "type_id", "place_id", "timestamp"),
    )


class MarketIndexSnapshot(Base):
    """Hourly snapshot of a commodity index (price/volume + concentration/liquidity)."""
    __tablename__ = "market_index_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    index_key = Column(String(20), nullable=False, index=True)  # plex, mineral, …
    timestamp = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    price_index = Column(Float, nullable=True)
    volume_index = Column(Float, nullable=True)
    top3_share = Column(Float, nullable=True)
    h_index = Column(Float, nullable=True)
    entropy = Column(Float, nullable=True)
    liquidity_index = Column(Float, nullable=True)


class AnalyticsCache(Base):
    """Pre-computed analytics payloads (indicators/risk) keyed by (kind, cache_key, window)."""
    __tablename__ = "analytics_cache"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(20), nullable=False)         # 'index' | 'tracking'
    cache_key = Column(String(80), nullable=False)    # index_key, or 'item:{id}:{place}'
    window = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False)
    computed_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("kind", "cache_key", "window", name="uq_analytics_cache"),
    )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Idempotent lightweight migrations (create_all does not ALTER existing tables).
_MIGRATIONS = [
    "ALTER TABLE organisations ADD COLUMN IF NOT EXISTS org_type VARCHAR(20) DEFAULT 'Personal'",
    "ALTER TABLE organisations ADD COLUMN IF NOT EXISTS corporation_id INTEGER",
    "ALTER TABLE organisations ADD COLUMN IF NOT EXISTS corporation_name VARCHAR(200)",
    "ALTER TABLE facilities ADD COLUMN IF NOT EXISTS organisation_id INTEGER",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS closed BOOLEAN DEFAULT FALSE",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS priority VARCHAR(10) DEFAULT 'medium'",
    "ALTER TABLE production_jobs ADD COLUMN IF NOT EXISTS windows INTEGER DEFAULT 1",
    "ALTER TABLE inventory ADD COLUMN IF NOT EXISTS flow VARCHAR(10) DEFAULT 'input'",
    "ALTER TABLE inventory ADD COLUMN IF NOT EXISTS item_status VARCHAR(12) DEFAULT 'in_stock'",
    "ALTER TABLE inventory ADD COLUMN IF NOT EXISTS sale_price DOUBLE PRECISION",
    "ALTER TYPE facilitytype ADD VALUE IF NOT EXISTS 'Athanor'",
    "ALTER TYPE facilitytype ADD VALUE IF NOT EXISTS 'Tatara'",
    # SQLAlchemy stores enum .name (uppercase); add those variants too
    "ALTER TYPE facilitytype ADD VALUE IF NOT EXISTS 'ATHANOR'",
    "ALTER TYPE facilitytype ADD VALUE IF NOT EXISTS 'TATARA'",
    # org public flag + user membership table
    "ALTER TABLE organisations ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT FALSE",
    """CREATE TABLE IF NOT EXISTS organisation_members (
        id SERIAL PRIMARY KEY,
        org_id INTEGER NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        role VARCHAR(20) NOT NULL DEFAULT 'JUNIOR',
        joined_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(org_id, user_id)
    )""",
    # track_prices: one composite index replaces the 3 single-column ones
    "CREATE INDEX IF NOT EXISTS ix_track_prices_type_place_ts ON track_prices (type_id, place_id, timestamp)",
    "DROP INDEX IF EXISTS ix_track_prices_type_id",
    "DROP INDEX IF EXISTS ix_track_prices_place_id",
    "DROP INDEX IF EXISTS ix_track_prices_timestamp",
]


def run_migrations():
    """Apply idempotent schema tweaks. Each runs in its own autocommit tx."""
    for stmt in _MIGRATIONS:
        try:
            with engine.connect() as conn:
                conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                conn.execute(text(stmt))
        except Exception as exc:  # noqa: BLE001 — best-effort, log and continue
            print(f"[migration] skipped: {stmt} -> {exc}")


# Schema bootstrap runs in the API container; the worker sets RUN_DB_BOOTSTRAP=0
# so the two containers don't race create_all/run_migrations on startup.
if os.getenv("RUN_DB_BOOTSTRAP", "1") == "1":
    Base.metadata.create_all(bind=engine)
    run_migrations()
