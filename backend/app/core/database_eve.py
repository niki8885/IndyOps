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

    id = Column(Integer, primary_key=True, default=1)
    build_id = Column(Integer, nullable=True)
    build_date = Column(String(30), nullable=True)
    updated_at = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Universe hierarchy
# ---------------------------------------------------------------------------

class EveCategory(EveBase):
    """invCategories — top-level item categories (Ship, Module, Charge…)."""
    __tablename__ = "eve_categories"

    category_id = Column(Integer, primary_key=True)
    category_name = Column(String(100), nullable=True)
    icon_id = Column(Integer, nullable=True)
    published = Column(Boolean, nullable=True)


class EveGroup(EveBase):
    """invGroups — item groups within a category."""
    __tablename__ = "eve_groups"

    group_id = Column(Integer, primary_key=True)
    category_id = Column(Integer, nullable=True, index=True)
    group_name = Column(String(100), nullable=True)
    icon_id = Column(Integer, nullable=True)
    published = Column(Boolean, nullable=True)
    anchored = Column(Boolean, nullable=True)
    anchorable = Column(Boolean, nullable=True)
    fittable_non_singleton = Column(Boolean, nullable=True)


class EveMarketGroup(EveBase):
    """invMarketGroups — market browser hierarchy."""
    __tablename__ = "eve_market_groups"

    market_group_id = Column(Integer, primary_key=True)
    parent_group_id = Column(Integer, nullable=True, index=True)
    market_group_name = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    icon_id = Column(Integer, nullable=True)
    has_types = Column(Boolean, nullable=True)


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

class EveType(EveBase):
    """invTypes — every item/type in the game."""
    __tablename__ = "eve_types"

    type_id = Column(Integer, primary_key=True)
    group_id = Column(Integer, nullable=True, index=True)
    type_name = Column(String(200), nullable=True, index=True)
    description = Column(Text, nullable=True)
    mass = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    capacity = Column(Float, nullable=True)
    portion_size = Column(Integer, nullable=True)
    race_id = Column(Integer, nullable=True)
    base_price = Column(Float, nullable=True)
    published = Column(Boolean, nullable=True, index=True)
    market_group_id = Column(Integer, nullable=True, index=True)
    icon_id = Column(Integer, nullable=True)
    graphic_id = Column(Integer, nullable=True)
    sound_id = Column(Integer, nullable=True)


class EveTypeMaterial(EveBase):
    """invTypeMaterials — what one *portion* of a type reprocesses/refines into.

    For ore and compressed ore this is the mineral yield; the row ``quantity`` is
    the perfect (100%) output for one ``EveType.portion_size`` batch of ``type_id``.
    Effective yield = quantity × facility/skill/rig multipliers × (1 − tax).
    Also covers reprocessing of modules/ships, but the Ore-Acquisition feature only
    reads ore → mineral rows. See [[indyops-chain-calculator]].
    """
    __tablename__ = "eve_type_materials"

    type_id = Column(Integer, primary_key=True, index=True)
    material_type_id = Column(Integer, primary_key=True, index=True)
    quantity = Column(BigInteger, nullable=True)


class EveMetaType(EveBase):
    """invMetaTypes — an item's tech level (meta group).

    ``meta_group_id``: 1 Tech I · 2 Tech II · 14 Tech III · 3 Storyline ·
    4 Faction · … Used to gate Basic vs Advanced engineering rigs (Basic rigs
    affect Tech I, Advanced rigs affect Tech II/III). Items with no row here
    (minerals, base hulls…) are treated as Tech I.
    """
    __tablename__ = "eve_meta_types"

    type_id = Column(Integer, primary_key=True)
    parent_type_id = Column(Integer, nullable=True, index=True)
    meta_group_id = Column(Integer, nullable=True, index=True)


# ---------------------------------------------------------------------------
# Industry / Blueprints
# ---------------------------------------------------------------------------

class EveBlueprint(EveBase):
    """industryBlueprints — max production limit per blueprint type."""
    __tablename__ = "eve_blueprints"

    type_id = Column(Integer, primary_key=True)
    max_production_limit = Column(Integer, nullable=True)


class EveActivityTime(EveBase):
    """industryActivity — base time (seconds) for each blueprint activity."""
    __tablename__ = "eve_activity_times"

    type_id = Column(Integer, primary_key=True)
    activity_id = Column(Integer, primary_key=True)
    time = Column(Integer, nullable=True)


class EveActivityMaterial(EveBase):
    """industryActivityMaterials — input materials per blueprint activity."""
    __tablename__ = "eve_activity_materials"

    type_id = Column(Integer, primary_key=True)
    activity_id = Column(Integer, primary_key=True)
    material_type_id = Column(Integer, primary_key=True, index=True)
    quantity = Column(BigInteger, nullable=True)


class EveActivityProduct(EveBase):
    """industryActivityProducts — output products per blueprint activity."""
    __tablename__ = "eve_activity_products"

    type_id = Column(Integer, primary_key=True)
    activity_id = Column(Integer, primary_key=True)
    product_type_id = Column(Integer, primary_key=True, index=True)
    quantity = Column(BigInteger, nullable=True)
    probability = Column(Float, nullable=True)


class EveActivitySkill(EveBase):
    """industryActivitySkills — skills required per blueprint activity."""
    __tablename__ = "eve_activity_skills"

    type_id = Column(Integer, primary_key=True)
    activity_id = Column(Integer, primary_key=True)
    skill_id = Column(Integer, primary_key=True, index=True)
    level = Column(SmallInteger, nullable=True)


class EveRigBonus(EveBase):
    """
    Engineering-rig industry bonuses, pivoted from dgmTypeAttributes.

    Bonuses are negative percentages (e.g. me_bonus -2.0 = 2% material saving).
    The effective bonus = base × security modifier for the structure's system
    (hi 1.0 / low 1.9 / null & WH 2.1).  attributeIDs:
      2594 ME, 2593 TE, 2595 cost, 2355 hi-sec, 2356 low-sec, 2357 null-sec.
    """
    __tablename__ = "eve_rig_bonuses"

    type_id = Column(Integer, primary_key=True)
    group_id = Column(Integer, nullable=True, index=True)
    me_bonus = Column(Float, nullable=True)
    te_bonus = Column(Float, nullable=True)
    cost_bonus = Column(Float, nullable=True)
    hisec_mod = Column(Float, nullable=True)
    lowsec_mod = Column(Float, nullable=True)
    nullsec_mod = Column(Float, nullable=True)


class EveReprocessingRig(EveBase):
    """
    Structure reprocessing-yield rigs (Standup M-Set … Reprocessing), pivoted from
    dgmTypeAttributes like :class:`EveRigBonus`.

    ``yield_bonus`` is the rig's reprocessing-yield bonus as a *positive* percentage
    (e.g. 2.0 = +2% yield). The effective bonus = ``yield_bonus × security modifier``
    for the refinery's system (hi 1.0 / low 1.9 / null & WH 2.1), matching the
    engineering-rig convention. ``group_id`` keys the rig's specialisation (general
    vs ore-specific). The attribute id carrying the bonus is resolved by *name* from
    dgmAttributeTypes at import time — see ``update_reprocessing_rigs``.
    """
    __tablename__ = "eve_reprocessing_rigs"

    type_id = Column(Integer, primary_key=True)
    group_id = Column(Integer, nullable=True, index=True)
    yield_bonus = Column(Float, nullable=True)
    hisec_mod = Column(Float, nullable=True)
    lowsec_mod = Column(Float, nullable=True)
    nullsec_mod = Column(Float, nullable=True)


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------

class EveRegion(EveBase):
    """mapRegions."""
    __tablename__ = "eve_regions"

    region_id = Column(Integer, primary_key=True)
    region_name = Column(String(100), nullable=True, index=True)
    faction_id = Column(Integer, nullable=True)
    x = Column(Float, nullable=True)
    y = Column(Float, nullable=True)
    z = Column(Float, nullable=True)


class EveConstellation(EveBase):
    """mapConstellations."""
    __tablename__ = "eve_constellations"

    constellation_id = Column(Integer, primary_key=True)
    region_id = Column(Integer, nullable=True, index=True)
    constellation_name = Column(String(100), nullable=True)
    faction_id = Column(Integer, nullable=True)
    x = Column(Float, nullable=True)
    y = Column(Float, nullable=True)
    z = Column(Float, nullable=True)


class EveSolarSystem(EveBase):
    """mapSolarSystems."""
    __tablename__ = "eve_solar_systems"

    solar_system_id = Column(Integer, primary_key=True)
    region_id = Column(Integer, nullable=True, index=True)
    constellation_id = Column(Integer, nullable=True, index=True)
    solar_system_name = Column(String(100), nullable=True, index=True)
    security = Column(Float, nullable=True)
    security_class = Column(String(10), nullable=True)
    faction_id = Column(Integer, nullable=True)
    x = Column(Float, nullable=True)
    y = Column(Float, nullable=True)
    z = Column(Float, nullable=True)


class EvePlanet(EveBase):
    """mapDenormalize rows for planets (groupID 7) — one row per planet in the universe.

    Lets the PI tab show a colony's planet name + physical radius + its celestial
    ``type_id`` (Temperate=11, Barren=2016, …) for the planet image, joined off the
    ESI colony's ``planet_id``. Loaded by ``update_sde.update_planets``.
    """
    __tablename__ = "eve_planets"

    planet_id = Column(Integer, primary_key=True)        # mapDenormalize.itemID
    type_id = Column(Integer, nullable=True)             # celestial planet type (Temperate/Barren/…)
    solar_system_id = Column(Integer, nullable=True, index=True)
    region_id = Column(Integer, nullable=True)
    planet_name = Column(String(100), nullable=True)     # e.g. "Tanoo III"
    radius = Column(Float, nullable=True)                # metres
    celestial_index = Column(Integer, nullable=True)     # planet's orbit number in the system


class EveStation(EveBase):
    """staStations — NPC stations."""
    __tablename__ = "eve_stations"

    station_id = Column(Integer, primary_key=True)
    station_name = Column(String(200), nullable=True, index=True)
    solar_system_id = Column(Integer, nullable=True, index=True)
    constellation_id = Column(Integer, nullable=True)
    region_id = Column(Integer, nullable=True, index=True)
    corporation_id = Column(Integer, nullable=True)
    station_type_id = Column(Integer, nullable=True)
    reprocessing_efficiency = Column(Float, nullable=True)
    reprocessing_stations_take = Column(Float, nullable=True)
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
