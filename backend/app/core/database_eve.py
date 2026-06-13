"""
EVE Online Static Data Export (SDE) database models.
Tables are populated/updated by app/tasks/update_sde.py
from https://www.fuzzwork.co.uk/dump/latest/csv/
"""
from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    Boolean, BigInteger, Text, DateTime, SmallInteger,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import SQLALCHEMY_DATABASE_URL

eve_engine = create_engine(SQLALCHEMY_DATABASE_URL)
EveSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=eve_engine)
EveBase = declarative_base()


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

class EveSdeMeta(EveBase):
    """Tracks the last successful SDE import (build ID + timestamp)."""
    __tablename__ = "eve_sde_meta"

    id         = Column(Integer, primary_key=True, default=1)
    build_id   = Column(Integer, nullable=True)
    build_date = Column(String(30), nullable=True)
    updated_at = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Universe hierarchy
# ---------------------------------------------------------------------------

class EveCategory(EveBase):
    """invCategories — top-level item categories (Ship, Module, Charge…)."""
    __tablename__ = "eve_categories"

    category_id   = Column(Integer, primary_key=True)
    category_name = Column(String(100), nullable=True)
    icon_id       = Column(Integer, nullable=True)
    published     = Column(Boolean, nullable=True)


class EveGroup(EveBase):
    """invGroups — item groups within a category."""
    __tablename__ = "eve_groups"

    group_id    = Column(Integer, primary_key=True)
    category_id = Column(Integer, nullable=True, index=True)
    group_name  = Column(String(100), nullable=True)
    icon_id     = Column(Integer, nullable=True)
    published   = Column(Boolean, nullable=True)
    anchored    = Column(Boolean, nullable=True)
    anchorable  = Column(Boolean, nullable=True)
    fittable_non_singleton = Column(Boolean, nullable=True)


class EveMarketGroup(EveBase):
    """invMarketGroups — market browser hierarchy."""
    __tablename__ = "eve_market_groups"

    market_group_id   = Column(Integer, primary_key=True)
    parent_group_id   = Column(Integer, nullable=True, index=True)
    market_group_name = Column(String(100), nullable=True)
    description       = Column(Text, nullable=True)
    icon_id           = Column(Integer, nullable=True)
    has_types         = Column(Boolean, nullable=True)


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

class EveType(EveBase):
    """invTypes — every item/type in the game."""
    __tablename__ = "eve_types"

    type_id          = Column(Integer, primary_key=True)
    group_id         = Column(Integer, nullable=True, index=True)
    type_name        = Column(String(200), nullable=True, index=True)
    description      = Column(Text, nullable=True)
    mass             = Column(Float, nullable=True)
    volume           = Column(Float, nullable=True)
    capacity         = Column(Float, nullable=True)
    portion_size     = Column(Integer, nullable=True)
    race_id          = Column(Integer, nullable=True)
    base_price       = Column(Float, nullable=True)
    published        = Column(Boolean, nullable=True, index=True)
    market_group_id  = Column(Integer, nullable=True, index=True)
    icon_id          = Column(Integer, nullable=True)
    graphic_id       = Column(Integer, nullable=True)
    sound_id         = Column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# Industry / Blueprints
# ---------------------------------------------------------------------------

class EveBlueprint(EveBase):
    """industryBlueprints — max production limit per blueprint type."""
    __tablename__ = "eve_blueprints"

    type_id               = Column(Integer, primary_key=True)
    max_production_limit  = Column(Integer, nullable=True)


class EveActivityTime(EveBase):
    """industryActivity — base time (seconds) for each blueprint activity."""
    __tablename__ = "eve_activity_times"

    type_id     = Column(Integer, primary_key=True)
    activity_id = Column(Integer, primary_key=True)
    time        = Column(Integer, nullable=True)


class EveActivityMaterial(EveBase):
    """industryActivityMaterials — input materials per blueprint activity."""
    __tablename__ = "eve_activity_materials"

    type_id          = Column(Integer, primary_key=True)
    activity_id      = Column(Integer, primary_key=True)
    material_type_id = Column(Integer, primary_key=True, index=True)
    quantity         = Column(BigInteger, nullable=True)


class EveActivityProduct(EveBase):
    """industryActivityProducts — output products per blueprint activity."""
    __tablename__ = "eve_activity_products"

    type_id         = Column(Integer, primary_key=True)
    activity_id     = Column(Integer, primary_key=True)
    product_type_id = Column(Integer, primary_key=True, index=True)
    quantity        = Column(BigInteger, nullable=True)
    probability     = Column(Float, nullable=True)


class EveActivitySkill(EveBase):
    """industryActivitySkills — skills required per blueprint activity."""
    __tablename__ = "eve_activity_skills"

    type_id     = Column(Integer, primary_key=True)
    activity_id = Column(Integer, primary_key=True)
    skill_id    = Column(Integer, primary_key=True, index=True)
    level       = Column(SmallInteger, nullable=True)


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------

class EveRegion(EveBase):
    """mapRegions."""
    __tablename__ = "eve_regions"

    region_id   = Column(Integer, primary_key=True)
    region_name = Column(String(100), nullable=True, index=True)
    faction_id  = Column(Integer, nullable=True)
    x = Column(Float, nullable=True)
    y = Column(Float, nullable=True)
    z = Column(Float, nullable=True)


class EveConstellation(EveBase):
    """mapConstellations."""
    __tablename__ = "eve_constellations"

    constellation_id   = Column(Integer, primary_key=True)
    region_id          = Column(Integer, nullable=True, index=True)
    constellation_name = Column(String(100), nullable=True)
    faction_id         = Column(Integer, nullable=True)
    x = Column(Float, nullable=True)
    y = Column(Float, nullable=True)
    z = Column(Float, nullable=True)


class EveSolarSystem(EveBase):
    """mapSolarSystems."""
    __tablename__ = "eve_solar_systems"

    solar_system_id   = Column(Integer, primary_key=True)
    region_id         = Column(Integer, nullable=True, index=True)
    constellation_id  = Column(Integer, nullable=True, index=True)
    solar_system_name = Column(String(100), nullable=True, index=True)
    security          = Column(Float, nullable=True)
    security_class    = Column(String(10), nullable=True)
    faction_id        = Column(Integer, nullable=True)
    x = Column(Float, nullable=True)
    y = Column(Float, nullable=True)
    z = Column(Float, nullable=True)


class EveStation(EveBase):
    """staStations — NPC stations."""
    __tablename__ = "eve_stations"

    station_id      = Column(Integer, primary_key=True)
    station_name    = Column(String(200), nullable=True, index=True)
    solar_system_id = Column(Integer, nullable=True, index=True)
    constellation_id= Column(Integer, nullable=True)
    region_id       = Column(Integer, nullable=True, index=True)
    corporation_id  = Column(Integer, nullable=True)
    station_type_id = Column(Integer, nullable=True)
    reprocessing_efficiency      = Column(Float, nullable=True)
    reprocessing_stations_take   = Column(Float, nullable=True)
    x = Column(Float, nullable=True)
    y = Column(Float, nullable=True)
    z = Column(Float, nullable=True)


def get_eve_db():
    db = EveSessionLocal()
    try:
        yield db
    finally:
        db.close()


EveBase.metadata.create_all(bind=eve_engine)
