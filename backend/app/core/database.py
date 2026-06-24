import os
from app.core.config import SQLALCHEMY_DATABASE_URL
from app.core.timeutil import utcnow
from sqlalchemy import (
    create_engine, Column, Integer, Enum,
    ForeignKey, String, DateTime, Date, Boolean, Float, Text, BigInteger, JSON,
    Index, UniqueConstraint, LargeBinary,
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

# FK targets / cascade strings reused across models (extracted to avoid duplicate literals)
_FK_ORGANISATIONS_ID = "organisations.id"
_FK_EMPLOYEES_ID = "employees.id"
_CASCADE_ALL_DELETE_ORPHAN = "all, delete-orphan"


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
    # 'private' | 'public' | 'group' — is_public mirrors (visibility == 'public') for back-compat
    visibility = Column(String(10), nullable=False, default="private", server_default="private")

    created_at = Column(DateTime, default=utcnow)

    owner_user = relationship("UserDB", back_populates="organisations")
    employees = relationship("Employee", back_populates="organisation")
    projects = relationship("Projects", back_populates="organisation")
    members = relationship("OrganisationMember", back_populates="organisation", cascade=_CASCADE_ALL_DELETE_ORPHAN)


class OrganisationMember(Base):
    """Links an IndyOps user to an org they have joined (distinct from EVE characters / employees)."""
    __tablename__ = "organisation_members"
    __table_args__ = (UniqueConstraint("org_id", "user_id"),)

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey(_FK_ORGANISATIONS_ID, ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False, default="JUNIOR")
    joined_at = Column(DateTime, default=utcnow)

    organisation = relationship("Organisation", back_populates="members")
    member_user = relationship("UserDB")


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)  # character name
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    character_id = Column(Integer, nullable=True)  # EVE character ID from ESI
    organisation_id = Column(Integer, ForeignKey(_FK_ORGANISATIONS_ID), nullable=True)

    status = Column(Enum(EmployeeType), nullable=False, index=True, default=EmployeeType.OTHER)

    added_at = Column(DateTime, default=utcnow)
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
    created_by = Column(Integer, ForeignKey(_FK_EMPLOYEES_ID), nullable=False)
    supervised_by = Column(Integer, ForeignKey(_FK_EMPLOYEES_ID), nullable=True)
    organisation_id = Column(Integer, ForeignKey(_FK_ORGANISATIONS_ID), nullable=False)

    org_project_code = Column(String, nullable=True, index=True)
    note = Column(String, nullable=True)
    project_type = Column(Enum(ProjectsType), nullable=False, index=True)
    status = Column(Enum(ProjectsStatus), nullable=False, index=True, default=ProjectsStatus.ACTIVE)
    repeatable = Column(Boolean, nullable=False, default=False)
    closed = Column(Boolean, nullable=False, default=False)
    priority = Column(String(10), nullable=False, default="medium")

    created_at = Column(DateTime, default=utcnow)
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
    organisation_id = Column(Integer, ForeignKey(_FK_ORGANISATIONS_ID), nullable=True, index=True)

    name = Column(String(200), nullable=False)
    facility_type = Column(Enum(FacilityType), nullable=False, index=True)
    # 'private' | 'public' | 'group' — public facilities can be followed + used by other users
    visibility = Column(String(10), nullable=False, default="private", server_default="private", index=True)

    tax = Column(Float, nullable=True)  # broker/facility tax %
    cost_bonus = Column(Float, nullable=True)  # material/time cost reduction %

    system_name = Column(String(200), nullable=True, index=True)
    solar_system_id = Column(Integer, nullable=True, index=True)  # SDE id → per-activity indices
    system_cost_index = Column(Float, nullable=True)  # ESI manufacturing cost index (legacy single value)

    # Rigs — stored as (eve_type_id, display name) pairs
    rig1_type_id = Column(Integer, nullable=True)
    rig1_name = Column(String(200), nullable=True)
    rig2_type_id = Column(Integer, nullable=True)
    rig2_name = Column(String(200), nullable=True)
    rig3_type_id = Column(Integer, nullable=True)
    rig3_name = Column(String(200), nullable=True)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, nullable=True)

    owner = relationship("UserDB", backref="facilities")


class FacilityFollow(Base):
    """A user's watch-list entry for someone else's *public* facility — lets them use it
    in their own calculations without owning it (distinct from org membership)."""
    __tablename__ = "facility_follows"
    __table_args__ = (UniqueConstraint("user_id", "facility_id", name="uq_facility_follow"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow)


class OrganisationFollow(Base):
    """A user's watch-list entry for a *public* organisation — lightweight tracking,
    separate from joining as a member (no role granted)."""
    __tablename__ = "organisation_follows"
    __table_args__ = (UniqueConstraint("user_id", "org_id", name="uq_org_follow"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id = Column(Integer, ForeignKey(_FK_ORGANISATIONS_ID, ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow)


class SystemCostIndex(Base):
    """ESI industry cost index per (solar system, activity), refreshed by a worker
    job. Activity key matches ESI ``/industry/systems/`` (``manufacturing``,
    ``copying``, ``invention``, ``researching_material_efficiency``,
    ``researching_time_efficiency``, ``reaction``). Values are fractions."""
    __tablename__ = "system_cost_indices"

    solar_system_id = Column(Integer, primary_key=True)
    activity = Column(String(40), primary_key=True)
    cost_index = Column(Float, nullable=False, default=0.0)
    updated_at = Column(DateTime, nullable=True)


class Blueprint(Base):
    """A blueprint the user owns — BPO (original, unlimited runs) or BPC (copy, with
    a run count and a purchase cost). The chain uses its ME/TE for the product it
    makes and folds a BPC's cost into the build."""
    __tablename__ = "blueprints"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    organisation_id = Column(Integer, ForeignKey(_FK_ORGANISATIONS_ID), nullable=True, index=True)

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

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, nullable=True)

    owner = relationship("UserDB", backref="blueprints")


class ProductionJob(Base):
    """PAK — a manufacturing production job/contract."""
    __tablename__ = "production_jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id"), nullable=True)

    # 'pak' = outsourced pack contract, 'indy' = internal planned job (Calculator → Add to plan)
    kind = Column(String(8), nullable=False, default="pak", server_default="pak", index=True)

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

    date_planned = Column(DateTime, default=utcnow)
    date_released = Column(DateTime, nullable=True)

    # Codes
    code = Column(String(100), nullable=True)
    contract_code = Column(String(500), nullable=True)
    note = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, nullable=True)

    owner = relationship("UserDB", backref="production_jobs")
    project = relationship("Projects", backref="production_jobs")
    facility = relationship("Facility", backref="production_jobs")
    status_events = relationship(
        "ProductionStatusEvent", backref="job",
        order_by="ProductionStatusEvent.at", cascade=_CASCADE_ALL_DELETE_ORPHAN,
    )


class ProductionStatusEvent(Base):
    """Append-only status history for a PAK production job — one row per transition
    (Planning → Preparing → In Progress → Completed/Cancelled), with timestamp, so the
    timeline is persisted. Mirrors DeliveryStatusEvent. See [[indyops-io13-ore-refining]]."""
    __tablename__ = "production_status_events"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("production_jobs.id"), nullable=False, index=True)
    from_status = Column(String(20), nullable=True)
    status = Column(String(20), nullable=False)
    note = Column(String(300), nullable=True)
    at = Column(DateTime, default=utcnow, nullable=False, index=True)


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

    # Set while a lot is attached to a pending delivery (it stays visible in the
    # warehouse). Cleared on delivery completion; the lot is deleted on failure.
    delivery_id = Column(Integer, ForeignKey("deliveries.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=utcnow)
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

    created_at = Column(DateTime, default=utcnow)

    owner = relationship("UserDB", backref="stock_movements")
    project = relationship("Projects", backref="stock_movements")
    job = relationship("ProductionJob", backref="stock_movements")


class Delivery(Base):
    """A shipment of warehouse stock from one location to a target system.

    Created in ``pending``; the chosen inventory lots stay in the warehouse but
    carry this delivery's id. On ``completed`` the lots move to the target
    location; on ``failed`` they are deleted. ``items_snapshot`` preserves the
    contents for display once the live lots are gone."""
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    organisation_id = Column(Integer, ForeignKey(_FK_ORGANISATIONS_ID), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)

    source_place = Column(String(200), nullable=True)   # origin warehouse / system
    source_system = Column(String(200), nullable=True)  # solar system the haul starts in
    target_system = Column(String(200), nullable=True)  # destination solar system
    target_place = Column(String(200), nullable=True)   # where lots land on completion

    mode = Column(String(10), nullable=False, default="regular")  # regular | jf
    sender_character = Column(String(200), nullable=True)
    sender_employee_id = Column(Integer, ForeignKey(_FK_EMPLOYEES_ID), nullable=True)

    # regular (gate freighter)
    jumps = Column(Integer, nullable=True)
    isk_per_jump_m3 = Column(Float, nullable=True)

    # jf (jump freighter)
    jf_ship = Column(String(40), nullable=True)         # Ark | Rhea | Nomad | Anshar
    isotope_name = Column(String(60), nullable=True)
    isotope_type_id = Column(Integer, nullable=True)
    light_years = Column(Float, nullable=True)
    isotopes_per_ly = Column(Float, nullable=True)
    trips = Column(Integer, nullable=True)
    round_trip = Column(Boolean, nullable=False, default=False)
    isotope_price = Column(Float, nullable=True)
    total_isotopes = Column(BigInteger, nullable=True)

    total_volume = Column(Float, nullable=True)
    total_value = Column(Float, nullable=True)   # collateral = ISK value of goods
    est_cost = Column(Float, nullable=True)      # computed shipping cost
    cost = Column(Float, nullable=False, default=0)  # contract reward (0 for now)

    code = Column(String(10), nullable=False, index=True)
    comment = Column(Text, nullable=True)
    status = Column(String(10), nullable=False, default="pending", index=True)  # pending|completed|failed
    items_snapshot = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime, nullable=True)

    owner = relationship("UserDB", backref="deliveries")
    project = relationship("Projects", backref="deliveries")
    organisation = relationship("Organisation", backref="deliveries")
    status_events = relationship(
        "DeliveryStatusEvent", backref="delivery",
        order_by="DeliveryStatusEvent.at", cascade=_CASCADE_ALL_DELETE_ORPHAN,
    )


class DeliveryStatusEvent(Base):
    """Append-only status history for a delivery — one row per transition, so the
    timeline (created → in transit → completed/failed, when and how long) is
    persisted rather than only the latest status. See [[indyops-io13-ore-refining]]."""
    __tablename__ = "delivery_status_events"

    id = Column(Integer, primary_key=True, index=True)
    delivery_id = Column(Integer, ForeignKey("deliveries.id"), nullable=False, index=True)
    from_status = Column(String(12), nullable=True)
    status = Column(String(12), nullable=False)
    note = Column(String(300), nullable=True)
    at = Column(DateTime, default=utcnow, nullable=False, index=True)


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
    created_at = Column(DateTime, default=utcnow)


class TrackedItem(Base):
    """A user's tracked item + which favourite places to track it in."""
    __tablename__ = "tracked_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type_id = Column(Integer, nullable=False)
    name = Column(String(200), nullable=False)
    place_ids = Column(JSON, nullable=True)  # [tracked_place_id, …]
    created_at = Column(DateTime, default=utcnow)


class TrackPrice(Base):
    """Hourly buy/sell/volume snapshot for a tracked (item, place)."""
    __tablename__ = "track_prices"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type_id = Column(Integer, nullable=False)
    place_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=utcnow)
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
    timestamp = Column(DateTime, nullable=False, default=utcnow, index=True)
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
    computed_at = Column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("kind", "cache_key", "window", name="uq_analytics_cache"),
    )


class PriceAlert(Base):
    """A user-defined financial alert on an index or a tracked item (the Agenda page).

    Watches either a commodity index (``target_kind='index'`` → ``index_key``) or a
    tracked item at one place (``target_kind='item'`` → ``item_id`` + ``place_id``).
    ``metric`` picks price vs volume; ``condition`` is an absolute crossing
    (above/below ``threshold``) or a % move over ``window_hours`` (pct_up/pct_down,
    threshold = percent). Fires → an AgendaNotification; one-shot alerts disarm
    (``active=False``) until re-armed, repeating alerts honour a cooldown."""
    __tablename__ = "price_alerts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    target_kind = Column(String(10), nullable=False)        # 'index' | 'item'
    index_key = Column(String(20), nullable=True)           # when target_kind='index'
    item_id = Column(Integer, nullable=True)                # tracked_items.id when 'item'
    place_id = Column(Integer, nullable=True)               # tracked_places.id (item alerts)
    metric = Column(String(10), nullable=False, default="price")     # 'price' | 'volume'
    condition = Column(String(12), nullable=False)          # above | below | pct_up | pct_down
    threshold = Column(Float, nullable=False)               # absolute value, or percent
    window_hours = Column(Integer, nullable=False, default=24)       # comparison window for pct
    active = Column(Boolean, nullable=False, default=True, index=True)
    repeat = Column(Boolean, nullable=False, default=False)
    note = Column(String(200), nullable=True)
    last_value = Column(Float, nullable=True)
    last_triggered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class AgendaNotification(Base):
    """A delivered notification in the Agenda feed (usually a fired PriceAlert)."""
    __tablename__ = "agenda_notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    alert_id = Column(Integer, nullable=True)               # source PriceAlert (kept if alert deleted)
    severity = Column(String(8), nullable=False, default="info")    # info | up | down
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, index=True)
    read_at = Column(DateTime, nullable=True)


class TradeCandidate(Base):
    """A precomputed cross-hub trade route (buy at one hub, sell at another).

    Current-state upsert table keyed by (item, buy_hub, sell_hub): each collector
    run overwrites the row. NOT a hypertable (no append-only history). Stores both
    a 'patient' (place a sell order) and 'instant' (sell into buy orders) margin;
    the query layer ranks by margin_pct_patient · volume_score."""
    __tablename__ = "trade_candidates"

    item_id = Column(Integer, primary_key=True)            # type_id
    buy_hub = Column(BigInteger, primary_key=True)         # source station_id
    sell_hub = Column(BigInteger, primary_key=True)        # destination station_id
    type_name = Column(String(200), nullable=True)
    buy_price = Column(Float, nullable=True)               # source lowest sell order
    sell_price_patient = Column(Float, nullable=True)      # dest lowest sell order
    sell_price_instant = Column(Float, nullable=True)      # dest highest buy order
    margin_pct_patient = Column(Float, nullable=True)
    margin_pct_instant = Column(Float, nullable=True)
    profit_isk_patient = Column(Float, nullable=True)
    profit_isk_instant = Column(Float, nullable=True)
    transport_cost = Column(Float, nullable=True)          # per-unit ISK
    item_volume_m3 = Column(Float, nullable=True)
    daily_volume = Column(Float, nullable=True)
    volatility_cv = Column(Float, nullable=True)
    volume_score = Column(Float, nullable=True)            # 0..1
    updated_at = Column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_trade_candidates_updated_at", "updated_at"),
        Index("ix_trade_candidates_margin_patient", "margin_pct_patient"),
    )


class StationTradeCandidate(Base):
    """A precomputed in-station flip (buy with a buy order, sell with a sell order
    at the same hub). Single-hub variant of TradeCandidate: no transport, broker
    fee charged twice. Current-state upsert keyed by (item, hub)."""
    __tablename__ = "station_trade_candidates"

    item_id = Column(Integer, primary_key=True)
    hub = Column(BigInteger, primary_key=True)             # station_id
    type_name = Column(String(200), nullable=True)
    buy_price = Column(Float, nullable=True)               # hub highest buy order
    sell_price = Column(Float, nullable=True)              # hub lowest sell order
    margin_pct = Column(Float, nullable=True)
    profit_isk = Column(Float, nullable=True)
    daily_volume = Column(Float, nullable=True)
    volatility_cv = Column(Float, nullable=True)
    volume_score = Column(Float, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_station_trade_candidates_updated_at", "updated_at"),
    )


class TradeTypeStat(Base):
    """History-derived liquidity/volatility per (region, type), refreshed by the
    slow trade-history job and read by the fast orders job. Current-state upsert."""
    __tablename__ = "trade_type_stats"

    region_id = Column(Integer, primary_key=True)
    type_id = Column(Integer, primary_key=True)
    daily_volume = Column(Float, nullable=True)
    volatility_cv = Column(Float, nullable=True)
    sample_days = Column(Integer, nullable=True)
    computed_at = Column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_trade_type_stats_computed_at", "computed_at"),
    )


class MarketForecast(Base):
    """Precomputed volume + price forecast per (region, type, horizon), refreshed by
    the forecasts worker over the liquid universe and read by /market/forecast so a
    request is a row read, not a recompute. The full forecast payload is stored as
    JSON; a few summary columns (signal / chosen models / MASE / turnover) are kept
    queryable for screeners. Current-state upsert. NOT a hypertable."""
    __tablename__ = "market_forecasts"

    region_id = Column(Integer, primary_key=True)
    type_id = Column(Integer, primary_key=True)
    horizon = Column(Integer, primary_key=True)
    vol_model = Column(String(20), nullable=True)
    vol_mase = Column(Float, nullable=True)
    price_model = Column(String(20), nullable=True)
    price_mase = Column(Float, nullable=True)
    signal_action = Column(String(12), nullable=True)
    signal_score = Column(Float, nullable=True)
    avg_turnover = Column(Float, nullable=True)
    payload = Column(JSON, nullable=False)
    computed_at = Column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_market_forecasts_computed_at", "computed_at"),
    )


class HaulCandidate(Base):
    """A precomputed, auto-discovered Jita → C-J6MT haul candidate.

    The haul scanner prices the most-liquid Jita items (daily volume floor, market
    category allowlist) against C-J and keeps the profitable ones, storing the best
    of the four methods' per-unit economics. Single route → keyed by item_id;
    current-state upsert (the whole table is replaced each scan). NOT a hypertable."""
    __tablename__ = "haul_candidates"

    item_id = Column(Integer, primary_key=True)            # type_id
    type_name = Column(String(200), nullable=True)
    category_id = Column(Integer, nullable=True)
    group_id = Column(Integer, nullable=True)              # SDE invGroup (Drugs = boosters)
    meta_group_id = Column(Integer, nullable=True)         # 1 T1 · 2 T2 · 4 Faction (NULL ⇒ T1)
    jita_buy = Column(Float, nullable=True)                # Jita best buy order
    jita_sell = Column(Float, nullable=True)               # Jita lowest sell order
    cj_buy = Column(Float, nullable=True)                  # C-J highest buy order
    cj_sell = Column(Float, nullable=True)                 # C-J lowest sell order
    item_volume_m3 = Column(Float, nullable=True)
    daily_volume = Column(Float, nullable=True)            # Jita daily traded units
    jita_buy_volume = Column(Float, nullable=True)         # units in standing Jita BUY orders (demand depth)
    best_method = Column(String(12), nullable=True)        # e.g. "sell_buy"
    profit_per_unit = Column(Float, nullable=True)
    margin_pct = Column(Float, nullable=True)              # ROI fraction of the best method
    transport_per_unit = Column(Float, nullable=True)      # default-rate courier cost / unit
    updated_at = Column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_haul_candidates_updated_at", "updated_at"),
        Index("ix_haul_candidates_margin", "margin_pct"),
        Index("ix_haul_candidates_meta", "meta_group_id"),
    )


class SimulationRun(Base):
    """A stored Monte-Carlo profit-simulation run (IO-22): the request snapshot,
    the risk-adjusted metrics, and the rendered per-run PDF. Roll-up reports are
    generated on demand from all runs sharing a project."""
    __tablename__ = "simulation_runs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)

    source = Column(String(12), nullable=False, default="chain")   # chain | production
    target_type_id = Column(Integer, nullable=False)
    label = Column(String(200), nullable=False)
    n_iterations = Column(Integer, nullable=False, default=25000)
    engine = Column(String(12), nullable=False, default="python")  # fortran | python

    params = Column(JSON, nullable=True)        # SimParams snapshot
    metrics = Column(JSON, nullable=False)      # SimMetrics (asdict)
    pdf = Column(LargeBinary, nullable=True)    # rendered per-run report

    created_at = Column(DateTime, default=utcnow, index=True)

    owner = relationship("UserDB", backref="simulation_runs")
    project = relationship("Projects", backref="simulation_runs")


class ScenarioAnalysis(Base):
    """A stored Scenario Simulation run (IO-23): the baseline metrics, every
    predefined/custom/composite scenario's metrics + comparison vs baseline, the
    risk-adjusted ranking, and the rendered per-analysis PDF. The combined
    'whole product' report is generated on demand from all analyses + simulation
    runs sharing a target_type_id."""
    __tablename__ = "scenario_analyses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)

    source = Column(String(12), nullable=False, default="chain")   # chain | production
    target_type_id = Column(Integer, nullable=False, index=True)
    label = Column(String(200), nullable=False)
    product_name = Column(String(200), nullable=True)
    engine = Column(String(12), nullable=False, default="python")  # fortran | python

    params = Column(JSON, nullable=True)        # SimParams snapshot
    baseline = Column(JSON, nullable=False)     # baseline SimMetrics (asdict)
    outcomes = Column(JSON, nullable=False)     # [ScenarioOutcome] (asdict)
    ranking = Column(JSON, nullable=True)       # [{rank,label,score}] incl. baseline
    pdf = Column(LargeBinary, nullable=True)    # rendered per-analysis report

    created_at = Column(DateTime, default=utcnow, index=True)

    owner = relationship("UserDB", backref="scenario_analyses")
    project = relationship("Projects", backref="scenario_analyses")


class ShareCode(Base):
    """A short, shareable code that maps to a calculator/chain request so anyone can
    reopen the exact build. Kept short (so the QR/barcode stay scannable) by storing the
    params server-side instead of in the code itself. Retention ~1 week; the store is
    capacity-bounded and evicts the oldest rows when full ("overwrite on no space")."""
    __tablename__ = "share_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(16), nullable=False, unique=True, index=True)
    source = Column(String(12), nullable=False, default="production")  # production | chain
    body = Column(JSON, nullable=False)            # the re-run request body
    created_at = Column(DateTime, default=utcnow, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)


class QuizResult(Base):
    """One Encyclopedia article-quiz attempt. Scores are kept per learning section
    (finance, …) per article so the account can show progress by section."""
    __tablename__ = "quiz_results"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    section = Column(String(40), nullable=False, index=True)   # e.g. "finance"
    article_key = Column(String(60), nullable=False, index=True)
    score = Column(Integer, nullable=False)                    # correct answers
    total = Column(Integer, nullable=False)                    # out of N
    created_at = Column(DateTime, default=utcnow, index=True)

    owner = relationship("UserDB", backref="quiz_results")


# ===========================================================================
# IO-24 — EVE SSO linked characters + synced ESI data
# ===========================================================================
class LinkedCharacter(Base):
    """An EVE character a user has linked via EVE SSO. Holds the (encrypted)
    OAuth tokens and the activation flag; the esi_* tables hang off character_id."""
    __tablename__ = "linked_characters"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    character_id = Column(Integer, nullable=False, unique=True, index=True)
    character_name = Column(String(200), nullable=False)
    corporation_id = Column(Integer, nullable=True)
    corporation_name = Column(String(200), nullable=True)
    alliance_id = Column(Integer, nullable=True)
    alliance_name = Column(String(200), nullable=True)
    owner_hash = Column(String(255), nullable=True)  # ESI 'owner' claim — detects char transfer

    scopes = Column(Text, nullable=True)             # space-separated granted scopes
    access_token_enc = Column(Text, nullable=True)   # Fernet-encrypted
    refresh_token_enc = Column(Text, nullable=True)  # Fernet-encrypted
    token_expires_at = Column(DateTime, nullable=True)

    wallet_balance = Column(Float, nullable=True)
    assets_value = Column(Float, nullable=True)       # ESI-average-priced assets (latest sync)
    total_sp = Column(BigInteger, nullable=True)

    # current location / ship / online — from the esi-location + clones scopes
    location_system_id = Column(Integer, nullable=True)
    location_id = Column(BigInteger, nullable=True)   # station or structure holding the char
    location_type = Column(String(20), nullable=True)  # 'station' | 'structure' | 'system'
    ship_type_id = Column(Integer, nullable=True)
    ship_name = Column(String(200), nullable=True)
    online = Column(Boolean, nullable=True)
    last_login = Column(DateTime, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)        # activation status
    status = Column(String(20), nullable=False, default="active")   # active|token_expired|invalid

    added_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, nullable=True)
    last_sync_at = Column(DateTime, nullable=True)

    owner = relationship("UserDB", backref="linked_characters")


class EsiWalletTransaction(Base):
    __tablename__ = "esi_wallet_transactions"
    __table_args__ = (UniqueConstraint("character_id", "transaction_id", name="uq_esi_tx"),)

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, nullable=False, index=True)
    transaction_id = Column(BigInteger, nullable=False)
    date = Column(DateTime, nullable=True)
    type_id = Column(Integer, nullable=True)
    quantity = Column(BigInteger, nullable=True)
    unit_price = Column(Float, nullable=True)
    is_buy = Column(Boolean, nullable=True)
    is_personal = Column(Boolean, nullable=True)
    client_id = Column(Integer, nullable=True)
    location_id = Column(BigInteger, nullable=True)
    journal_ref_id = Column(BigInteger, nullable=True)


class EsiSkill(Base):
    __tablename__ = "esi_skills"
    __table_args__ = (UniqueConstraint("character_id", "skill_id", name="uq_esi_skill"),)

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, nullable=False, index=True)
    skill_id = Column(Integer, nullable=False)
    skillpoints = Column(BigInteger, nullable=True)
    trained_level = Column(Integer, nullable=True)
    active_level = Column(Integer, nullable=True)


class EsiAsset(Base):
    __tablename__ = "esi_assets"
    __table_args__ = (UniqueConstraint("character_id", "item_id", name="uq_esi_asset"),)

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, nullable=False, index=True)
    item_id = Column(BigInteger, nullable=False)
    type_id = Column(Integer, nullable=True)
    quantity = Column(BigInteger, nullable=True)
    location_id = Column(BigInteger, nullable=True)
    location_flag = Column(String(60), nullable=True)
    location_type = Column(String(30), nullable=True)
    is_singleton = Column(Boolean, nullable=True)
    is_blueprint_copy = Column(Boolean, nullable=True)


class EsiBlueprintCopy(Base):
    """A character's owned blueprints (BPOs and BPCs), replaced each sync.

    ``runs == -1`` (ESI also sends ``quantity == -1``) marks a BPO/original with
    unlimited runs; a BPC (copy) has ``quantity == -2`` and a positive ``runs``.
    ``is_bpo`` is derived in the read layer (``runs < 0``), not stored.
    """
    __tablename__ = "esi_blueprints"
    __table_args__ = (UniqueConstraint("character_id", "item_id", name="uq_esi_blueprint"),)

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, nullable=False, index=True)
    item_id = Column(BigInteger, nullable=False)        # the blueprint instance
    type_id = Column(Integer, nullable=True)            # blueprint type (e.g. Rifter Blueprint)
    material_efficiency = Column(Integer, nullable=True)
    time_efficiency = Column(Integer, nullable=True)
    runs = Column(Integer, nullable=True)               # -1 = BPO (unlimited)
    quantity = Column(Integer, nullable=True)           # -1 = original, -2 = copy
    location_id = Column(BigInteger, nullable=True)
    location_flag = Column(String(60), nullable=True)


class EsiStructure(Base):
    """
    Cache of resolved Upwell structure names (IO asset-location recursion).

    Player structure ids only become names via ESI /universe/structures/{id}/,
    which needs the read_structures scope + docking access. Keyed globally by
    structure_id and shared across characters: once any character with access
    resolves a name it's reused. ``error`` records a 403/404 so we can back off
    instead of re-hammering, and a different character can retry later.
    """
    __tablename__ = "esi_structures"

    structure_id = Column(BigInteger, primary_key=True)
    name = Column(String(255), nullable=True)
    solar_system_id = Column(Integer, nullable=True)
    type_id = Column(Integer, nullable=True)
    error = Column(String(20), nullable=True)        # 'forbidden' | 'not_found' | 'error'
    updated_at = Column(DateTime, nullable=True)      # last fetch attempt


class EsiImplant(Base):
    """A character's currently-plugged implants (replaced each sync)."""
    __tablename__ = "esi_implants"
    __table_args__ = (UniqueConstraint("character_id", "type_id", name="uq_esi_implant"),)

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, nullable=False, index=True)
    type_id = Column(Integer, nullable=False)


class CharacterWealthSnapshot(Base):
    """Append-only wealth history (one row per sync) backing the overview's plot."""
    __tablename__ = "character_wealth_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    liquid = Column(Float, nullable=True)         # wallet balance
    assets_value = Column(Float, nullable=True)   # ESI-average-priced assets
    total = Column(Float, nullable=True)          # liquid + assets


class EsiMiningLedger(Base):
    """A character's mining ledger (one row per day × ore type × system).

    ESI only keeps ~30 days, so sync **upserts** (not replace) — older rows persist
    so the journal's month/quarter/year reports accumulate history over time."""
    __tablename__ = "esi_mining_ledger"
    __table_args__ = (UniqueConstraint("character_id", "date", "type_id", "solar_system_id",
                                       name="uq_mining_entry"),)

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    type_id = Column(Integer, nullable=False)
    solar_system_id = Column(Integer, nullable=True)
    quantity = Column(BigInteger, nullable=True)


class CharacterSettings(Base):
    """Per-character settings, edited in the Character Settings tab — the mining
    journal knobs plus role/grouping flags."""
    __tablename__ = "character_settings"

    character_id = Column(Integer, primary_key=True)   # LinkedCharacter.character_id
    mining_tax_pct = Column(Float, nullable=False, default=0.0)      # corp mining tax %
    price_basis = Column(String(10), nullable=False, default="sell")  # buy | sell | split
    refine_base_yield = Column(Float, nullable=False, default=0.50)   # structure base yield

    # role / grouping criteria
    favorite = Column(Boolean, nullable=False, default=False)         # pin to top of the list
    track_wealth = Column(Boolean, nullable=False, default=True)      # count in overall capital
    track_production = Column(Boolean, nullable=False, default=True)  # include in the common chain
    is_manufacturer = Column(Boolean, nullable=False, default=False)  # manufacturing char
    is_trader = Column(Boolean, nullable=False, default=False)        # trading char
    group_name = Column(String(60), nullable=True)                   # free-text custom group


class MiningTaxWriteoff(Base):
    """A persisted 'tax written off' record for a journal period (the Списать налог button)."""
    __tablename__ = "mining_tax_writeoffs"
    __table_args__ = (UniqueConstraint("user_id", "scope", "character_id", "period_type", "period_key",
                                       name="uq_mining_writeoff"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    character_id = Column(Integer, nullable=True)        # null when scope = 'all'
    scope = Column(String(12), nullable=False)           # 'character' | 'all'
    period_type = Column(String(8), nullable=False)      # day | month | quarter | year
    period_key = Column(String(16), nullable=False)      # e.g. 2026-06, 2026-Q2, 2026
    gross_value = Column(Float, nullable=True)
    tax_pct = Column(Float, nullable=True)
    tax_amount = Column(Float, nullable=True)
    net_value = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=True)


class EsiContract(Base):
    __tablename__ = "esi_contracts"
    __table_args__ = (UniqueConstraint("character_id", "contract_id", name="uq_esi_contract"),)

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, nullable=False, index=True)
    contract_id = Column(BigInteger, nullable=False)
    type = Column(String(30), nullable=True)
    status = Column(String(30), nullable=True)
    for_corp = Column(Boolean, nullable=True)
    issuer_id = Column(Integer, nullable=True)
    assignee_id = Column(Integer, nullable=True)
    acceptor_id = Column(Integer, nullable=True)
    date_issued = Column(DateTime, nullable=True)
    date_expired = Column(DateTime, nullable=True)
    date_accepted = Column(DateTime, nullable=True)
    date_completed = Column(DateTime, nullable=True)
    price = Column(Float, nullable=True)
    reward = Column(Float, nullable=True)
    collateral = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    title = Column(String(255), nullable=True)
    availability = Column(String(30), nullable=True)
    start_location_id = Column(BigInteger, nullable=True)
    end_location_id = Column(BigInteger, nullable=True)


class EsiIndustryJob(Base):
    __tablename__ = "esi_industry_jobs"
    __table_args__ = (UniqueConstraint("character_id", "job_id", name="uq_esi_job"),)

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, nullable=False, index=True)
    job_id = Column(BigInteger, nullable=False)
    activity_id = Column(Integer, nullable=True)
    blueprint_type_id = Column(Integer, nullable=True)
    blueprint_id = Column(BigInteger, nullable=True)
    product_type_id = Column(Integer, nullable=True)
    runs = Column(Integer, nullable=True)
    licensed_runs = Column(Integer, nullable=True)
    status = Column(String(30), nullable=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    facility_id = Column(BigInteger, nullable=True)
    station_id = Column(BigInteger, nullable=True)
    cost = Column(Float, nullable=True)
    probability = Column(Float, nullable=True)


class EsiStanding(Base):
    """A character's NPC standing (toward a faction / npc_corp / agent). Used to
    estimate the broker-fee reduction a selling character gets."""
    __tablename__ = "esi_standings"
    __table_args__ = (UniqueConstraint("character_id", "from_id", name="uq_esi_standing"),)

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, nullable=False, index=True)
    from_id = Column(Integer, nullable=False)
    from_type = Column(String(20), nullable=True)  # 'faction' | 'npc_corp' | 'agent'
    standing = Column(Float, nullable=True)


class EsiMarketOrder(Base):
    """A character's *active* market orders (buy + sell), replaced each sync.

    ESI /orders returns only currently-open orders, so this is a full snapshot
    (delete-then-insert like jobs/blueprints). ``region_id`` comes straight from ESI;
    ``location_id`` is the station or Upwell structure the order sits in."""
    __tablename__ = "esi_market_orders"
    __table_args__ = (UniqueConstraint("character_id", "order_id", name="uq_esi_market_order"),)

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, nullable=False, index=True)
    order_id = Column(BigInteger, nullable=False)
    type_id = Column(Integer, nullable=True, index=True)
    region_id = Column(Integer, nullable=True)
    location_id = Column(BigInteger, nullable=True)
    is_buy_order = Column(Boolean, nullable=True)
    price = Column(Float, nullable=True)
    volume_total = Column(BigInteger, nullable=True)
    volume_remain = Column(BigInteger, nullable=True)
    min_volume = Column(BigInteger, nullable=True)
    range = Column(String(20), nullable=True)
    duration = Column(Integer, nullable=True)
    escrow = Column(Float, nullable=True)            # buy orders only
    issued = Column(DateTime, nullable=True)
    synced_at = Column(DateTime, nullable=True)


class BankLedgerEntry(Base):
    """A credit to a user's in-app balance from an in-game ISK donation to the bank
    corporation (wallet-journal ``player_donation``). Append-only and idempotent on
    the journal ``ref_id``. Amount kept in integer Penny (1 ISK = 100 Penny) so
    balances sum exactly (see ``services/currency.py``)."""
    __tablename__ = "bank_ledger_entries"
    __table_args__ = (UniqueConstraint("ref_id", name="uq_bank_ledger_ref"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    character_id = Column(Integer, nullable=True, index=True)   # the donor character
    ref_id = Column(BigInteger, nullable=False)                 # ESI wallet-journal entry id
    amount_penny = Column(BigInteger, nullable=False)           # positive credit, 1 ISK = 100 Penny
    amount_isk = Column(Float, nullable=True)
    date = Column(DateTime, nullable=True)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=True)


class EsiWalletEntry(Base):
    """Income wallet-journal entries we care about for the Tracking income ledgers
    (Mission rewards + Ratting bounty/ESS). Captured during the ESI sync from the
    wallet journal — only the ``ref_type``s in ``update_esi._INCOME_REF_TYPES`` are
    stored, so the table stays bounded. Append-only / idempotent on the journal
    ``ref_id`` (per character). ESI keeps ~30 days of journal, so history accumulates
    forward from the first sync."""
    __tablename__ = "esi_wallet_entries"
    __table_args__ = (UniqueConstraint("character_id", "ref_id", name="uq_esi_wallet_entry"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    character_id = Column(Integer, nullable=False, index=True)
    ref_id = Column(BigInteger, nullable=False)              # ESI wallet-journal entry id
    ref_type = Column(String(40), nullable=True, index=True)  # agent_mission_reward, bounty_prizes, …
    amount = Column(Float, nullable=True)                    # ISK (positive = income)
    balance = Column(Float, nullable=True)                   # wallet balance after the entry
    date = Column(DateTime, nullable=True, index=True)
    first_party_id = Column(Integer, nullable=True)          # agent (missions) / NPC (bounties)
    second_party_id = Column(Integer, nullable=True)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=True)


class ContractAnnotation(Base):
    """A user's private tags + note for one contract (Deliverly courier tracker).

    ``EsiContract`` is ESI-synced and shared, so user annotations live here, keyed by
    (user_id, contract_id). ``tags`` is a comma-separated free-text list."""
    __tablename__ = "contract_annotations"
    __table_args__ = (UniqueConstraint("user_id", "contract_id", name="uq_contract_annotation"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    contract_id = Column(BigInteger, nullable=False, index=True)
    tags = Column(String(255), nullable=True)
    note = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=True)


class CourierRouteCache(Base):
    """Cached gate-jump count between a courier contract's start/end location, so the
    ESI /route call is made at most once per route (routes are static). Keyed by the
    (start_location_id, end_location_id) pair."""
    __tablename__ = "courier_route_cache"
    __table_args__ = (UniqueConstraint("start_location_id", "end_location_id", name="uq_courier_route"),)

    id = Column(Integer, primary_key=True, index=True)
    start_location_id = Column(BigInteger, nullable=False)
    end_location_id = Column(BigInteger, nullable=False)
    start_system_id = Column(Integer, nullable=True)
    end_system_id = Column(Integer, nullable=True)
    jumps = Column(Integer, nullable=True)
    computed_at = Column(DateTime, nullable=True)


class LootAppraisal(Base):
    """A saved, ISK-valued loot paste tied to the Ratting income tracker. ``value_isk``
    is a snapshot taken at parse time; ``items_json`` keeps the parsed line items."""
    __tablename__ = "loot_appraisals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    character_id = Column(Integer, nullable=True)
    date = Column(DateTime, nullable=True, index=True)
    title = Column(String(120), nullable=True)
    tags = Column(String(255), nullable=True)
    raw_text = Column(Text, nullable=True)
    pricing = Column(String(20), nullable=True)             # jita_sell | jita_buy
    value_isk = Column(Float, nullable=True)
    items_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=True)


class EsiNameCache(Base):
    """Cache of resolved EVE ids → name/category (via /universe/names/), used for
    mission agent names and contract counterparties so name lookups don't hit ESI on
    every page load."""
    __tablename__ = "esi_name_cache"

    id = Column(BigInteger, primary_key=True)   # the EVE id
    name = Column(String(255), nullable=True)
    category = Column(String(40), nullable=True)
    updated_at = Column(DateTime, nullable=True)


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
    # deliveries (Inventory → Delivery feature) + the inventory link column
    """CREATE TABLE IF NOT EXISTS deliveries (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        organisation_id INTEGER REFERENCES organisations(id),
        project_id INTEGER REFERENCES projects(id),
        source_place VARCHAR(200),
        source_system VARCHAR(200),
        target_system VARCHAR(200),
        target_place VARCHAR(200),
        mode VARCHAR(10) NOT NULL DEFAULT 'regular',
        sender_character VARCHAR(200),
        sender_employee_id INTEGER REFERENCES employees(id),
        jumps INTEGER,
        isk_per_jump_m3 DOUBLE PRECISION,
        jf_ship VARCHAR(40),
        isotope_name VARCHAR(60),
        isotope_type_id INTEGER,
        light_years DOUBLE PRECISION,
        isotopes_per_ly DOUBLE PRECISION,
        trips INTEGER,
        round_trip BOOLEAN NOT NULL DEFAULT FALSE,
        isotope_price DOUBLE PRECISION,
        total_isotopes BIGINT,
        total_volume DOUBLE PRECISION,
        total_value DOUBLE PRECISION,
        est_cost DOUBLE PRECISION,
        cost DOUBLE PRECISION NOT NULL DEFAULT 0,
        code VARCHAR(10) NOT NULL,
        comment TEXT,
        status VARCHAR(10) NOT NULL DEFAULT 'pending',
        items_snapshot JSON,
        created_at TIMESTAMP DEFAULT NOW(),
        completed_at TIMESTAMP
    )""",
    "CREATE INDEX IF NOT EXISTS ix_deliveries_user_id ON deliveries (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_deliveries_status ON deliveries (status)",
    "ALTER TABLE inventory ADD COLUMN IF NOT EXISTS delivery_id INTEGER REFERENCES deliveries(id)",
    "CREATE INDEX IF NOT EXISTS ix_inventory_delivery_id ON inventory (delivery_id)",
    # linked_characters overview columns (Alembic 0013) — mirrored here because the
    # Alembic upgrade is best-effort and never lands on a create_all-built DB, while
    # create_all itself cannot ALTER the pre-existing linked_characters table.
    "ALTER TABLE linked_characters ADD COLUMN IF NOT EXISTS corporation_name VARCHAR(200)",
    "ALTER TABLE linked_characters ADD COLUMN IF NOT EXISTS alliance_name VARCHAR(200)",
    "ALTER TABLE linked_characters ADD COLUMN IF NOT EXISTS assets_value DOUBLE PRECISION",
    "ALTER TABLE linked_characters ADD COLUMN IF NOT EXISTS location_system_id INTEGER",
    "ALTER TABLE linked_characters ADD COLUMN IF NOT EXISTS location_id BIGINT",
    "ALTER TABLE linked_characters ADD COLUMN IF NOT EXISTS location_type VARCHAR(20)",
    "ALTER TABLE linked_characters ADD COLUMN IF NOT EXISTS ship_type_id INTEGER",
    "ALTER TABLE linked_characters ADD COLUMN IF NOT EXISTS ship_name VARCHAR(200)",
    "ALTER TABLE linked_characters ADD COLUMN IF NOT EXISTS online BOOLEAN",
    "ALTER TABLE linked_characters ADD COLUMN IF NOT EXISTS last_login TIMESTAMP",
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
