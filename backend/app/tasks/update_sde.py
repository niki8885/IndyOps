import bz2
import csv
from app.core.timeutil import utcnow
import io
import logging
import re
import time
from typing import Any

import requests
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database_eve import (
    EveSessionLocal,
    EveBase,
    eve_engine,
    EveSdeMeta,
    EveCategory,
    EveGroup,
    EveMarketGroup,
    EveType,
    EveTypeMaterial,
    EveMetaType,
    EveBlueprint,
    EveActivityTime,
    EveActivityMaterial,
    EveActivityProduct,
    EveActivitySkill,
    EveRegion,
    EveConstellation,
    EveSolarSystem,
    EveStation,
    EvePlanet,
    EveRigBonus,
    EveReprocessingRig,
)

_PLANET_GROUP_ID = 7   # invGroups: Planet (category 2 Celestial)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.fuzzwork.co.uk/dump/latest/csv/"
INDEX_URL = "https://www.fuzzwork.co.uk/dump/latest/"
CHUNK_SIZE = 2000
REQUEST_TIMEOUT = 120


# ---------------------------------------------------------------------------
# Version detection
# ---------------------------------------------------------------------------

def fetch_latest_build_info() -> tuple[int | None, str | None]:
    """Parse the fuzzwork index page and return (build_id, build_date)."""
    try:
        resp = requests.get(INDEX_URL, timeout=30)
        resp.raise_for_status()
        match = re.search(r"sdeyaml_postgres_(\d+)_(\d{8}_\d{6})\.pgdump", resp.text)
        if match:
            return int(match.group(1)), match.group(2)
    except Exception as exc:
        logger.warning("Could not fetch build info: %s", exc)
    return None, None


def current_build_id(db) -> int | None:
    meta = db.query(EveSdeMeta).filter(EveSdeMeta.id == 1).first()
    return meta.build_id if meta else None


# ---------------------------------------------------------------------------
# CSV download + parse
# ---------------------------------------------------------------------------

def _download_csv(table_name: str) -> list[dict]:
    """
    Download a CSV table from fuzzwork and return rows as dicts.

    Fuzzwork now serves uncompressed `.csv`; we try that first and fall back
    to the legacy `.csv.bz2` for resilience.  `utf-8-sig` strips any BOM and
    csv.DictReader handles quoted fields containing embedded newlines.
    """
    last_exc: Exception | None = None
    for suffix, compressed in ((".csv", False), (".csv.bz2", True)):
        url = f"{BASE_URL}{table_name}{suffix}"
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            logger.info("Downloaded %s (%d bytes)", url, len(resp.content))
            data = bz2.decompress(resp.content) if compressed else resp.content
            reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
            return list(reader)
        except requests.HTTPError as exc:
            last_exc = exc
            if resp.status_code == 404:
                continue  # try the next format
            raise
    raise last_exc  # both formats 404'd


def _coerce(row: dict, key: str, cast, default=None):
    val = row.get(key, "")
    if val == "" or val is None:
        return default
    try:
        return cast(val)
    except (ValueError, TypeError):
        return default


def _bool(val: str | None) -> bool | None:
    if val in (None, ""):
        return None
    return val.strip().lower() in ("1", "true", "t", "yes")


def _dedup(rows: list[dict], *keys: str) -> list[dict]:
    """
    Drop rows with duplicate values across `keys`, keeping the last occurrence.

    Postgres ``INSERT ... ON CONFLICT DO UPDATE`` raises a CardinalityViolation
    if the same constrained key appears twice in one statement, and some
    fuzzwork tables (e.g. industryActivitySkills) contain exact duplicates.
    """
    seen: dict[tuple, dict] = {}
    for r in rows:
        seen[tuple(r.get(k) for k in keys)] = r
    return list(seen.values())


# ---------------------------------------------------------------------------
# Table updaters  (each returns row count upserted)
# ---------------------------------------------------------------------------

def _upsert_chunks(db, stmt_builder, rows: list[dict], chunk: int = CHUNK_SIZE) -> int:
    total = 0
    for i in range(0, len(rows), chunk):
        batch = rows[i: i + chunk]
        stmt = stmt_builder(batch)
        db.execute(stmt)
        total += len(batch)
    db.commit()
    return total


def update_categories(db) -> int:
    raw = _download_csv("invCategories")

    def build(batch):
        values = [
            {
                "category_id": _coerce(r, "categoryID", int),
                "category_name": r.get("categoryName", "")[:100],
                "icon_id": _coerce(r, "iconID", int),
                "published": _bool(r.get("published")),
            }
            for r in batch
        ]
        stmt = pg_insert(EveCategory).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["category_id"],
            set_={c: stmt.excluded[c] for c in ("category_name", "icon_id", "published")},
        )

    return _upsert_chunks(db, build, raw)


def update_groups(db) -> int:
    raw = _download_csv("invGroups")

    def build(batch):
        values = [
            {
                "group_id": _coerce(r, "groupID", int),
                "category_id": _coerce(r, "categoryID", int),
                "group_name": r.get("groupName", "")[:100],
                "icon_id": _coerce(r, "iconID", int),
                "published": _bool(r.get("published")),
                "anchored": _bool(r.get("anchored")),
                "anchorable": _bool(r.get("anchorable")),
                "fittable_non_singleton": _bool(r.get("fittableNonSingleton")),
            }
            for r in batch
        ]
        stmt = pg_insert(EveGroup).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["group_id"],
            set_={c: stmt.excluded[c] for c in ("category_id", "group_name", "icon_id", "published")},
        )

    return _upsert_chunks(db, build, raw)


def update_market_groups(db) -> int:
    raw = _download_csv("invMarketGroups")

    def build(batch):
        values = [
            {
                "market_group_id": _coerce(r, "marketGroupID", int),
                "parent_group_id": _coerce(r, "parentGroupID", int),
                "market_group_name": r.get("marketGroupName", "")[:100],
                "description": r.get("description") or None,
                "icon_id": _coerce(r, "iconID", int),
                "has_types": _bool(r.get("hasTypes")),
            }
            for r in batch
        ]
        stmt = pg_insert(EveMarketGroup).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["market_group_id"],
            set_={c: stmt.excluded[c] for c in
                  ("parent_group_id", "market_group_name", "description", "icon_id", "has_types")},
        )

    return _upsert_chunks(db, build, raw)


def update_types(db) -> int:
    raw = _download_csv("invTypes")

    def build(batch):
        values = [
            {
                "type_id": _coerce(r, "typeID", int),
                "group_id": _coerce(r, "groupID", int),
                "type_name": (r.get("typeName") or "")[:200],
                "description": r.get("description") or None,
                "mass": _coerce(r, "mass", float),
                "volume": _coerce(r, "volume", float),
                "capacity": _coerce(r, "capacity", float),
                "portion_size": _coerce(r, "portionSize", int),
                "race_id": _coerce(r, "raceID", int),
                "base_price": _coerce(r, "basePrice", float),
                "published": _bool(r.get("published")),
                "market_group_id": _coerce(r, "marketGroupID", int),
                "icon_id": _coerce(r, "iconID", int),
                "graphic_id": _coerce(r, "graphicID", int),
                "sound_id": _coerce(r, "soundID", int),
            }
            for r in batch
        ]
        stmt = pg_insert(EveType).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["type_id"],
            set_={c: stmt.excluded[c] for c in (
                "group_id", "type_name", "description", "mass", "volume",
                "capacity", "portion_size", "race_id", "base_price",
                "published", "market_group_id", "icon_id", "graphic_id", "sound_id",
            )},
        )

    return _upsert_chunks(db, build, raw)


def update_meta_types(db) -> int:
    """Item tech level (meta group) from invMetaTypes — gates Basic/Advanced rigs."""
    raw = _download_csv("invMetaTypes")

    def build(batch):
        values = [
            {
                "type_id": _coerce(r, "typeID", int),
                "parent_type_id": _coerce(r, "parentTypeID", int),
                "meta_group_id": _coerce(r, "metaGroupID", int),
            }
            for r in batch
        ]
        stmt = pg_insert(EveMetaType).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["type_id"],
            set_={c: stmt.excluded[c] for c in ("parent_type_id", "meta_group_id")},
        )

    return _upsert_chunks(db, build, raw)


def update_type_materials(db) -> int:
    """invTypeMaterials — reprocessing/refining yields (ore → minerals, and more)."""
    raw = _dedup(_download_csv("invTypeMaterials"), "typeID", "materialTypeID")

    def build(batch):
        values = [
            {
                "type_id": _coerce(r, "typeID", int),
                "material_type_id": _coerce(r, "materialTypeID", int),
                "quantity": _coerce(r, "quantity", int),
            }
            for r in batch
        ]
        stmt = pg_insert(EveTypeMaterial).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["type_id", "material_type_id"],
            set_={"quantity": stmt.excluded["quantity"]},
        )

    return _upsert_chunks(db, build, raw)


def update_blueprints(db) -> int:
    raw = _download_csv("industryBlueprints")

    def build(batch):
        values = [
            {
                "type_id": _coerce(r, "typeID", int),
                "max_production_limit": _coerce(r, "maxProductionLimit", int),
            }
            for r in batch
        ]
        stmt = pg_insert(EveBlueprint).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["type_id"],
            set_={"max_production_limit": stmt.excluded["max_production_limit"]},
        )

    return _upsert_chunks(db, build, raw)


def update_activity_times(db) -> int:
    raw = _dedup(_download_csv("industryActivity"), "typeID", "activityID")

    def build(batch):
        values = [
            {
                "type_id": _coerce(r, "typeID", int),
                "activity_id": _coerce(r, "activityID", int),
                "time": _coerce(r, "time", int),
            }
            for r in batch
        ]
        stmt = pg_insert(EveActivityTime).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["type_id", "activity_id"],
            set_={"time": stmt.excluded["time"]},
        )

    return _upsert_chunks(db, build, raw)


def update_activity_materials(db) -> int:
    raw = _dedup(_download_csv("industryActivityMaterials"), "typeID", "activityID", "materialTypeID")

    def build(batch):
        values = [
            {
                "type_id": _coerce(r, "typeID", int),
                "activity_id": _coerce(r, "activityID", int),
                "material_type_id": _coerce(r, "materialTypeID", int),
                "quantity": _coerce(r, "quantity", int),
            }
            for r in batch
        ]
        stmt = pg_insert(EveActivityMaterial).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["type_id", "activity_id", "material_type_id"],
            set_={"quantity": stmt.excluded["quantity"]},
        )

    return _upsert_chunks(db, build, raw)


def update_activity_products(db) -> int:
    raw = _dedup(_download_csv("industryActivityProducts"), "typeID", "activityID", "productTypeID")

    def build(batch):
        values = [
            {
                "type_id": _coerce(r, "typeID", int),
                "activity_id": _coerce(r, "activityID", int),
                "product_type_id": _coerce(r, "productTypeID", int),
                "quantity": _coerce(r, "quantity", int),
            }
            for r in batch
        ]
        stmt = pg_insert(EveActivityProduct).values(values)
        # NB: don't touch ``probability`` here — it lives in a *separate* fuzzwork table
        # (industryActivityProbabilities) and is populated by update_activity_probabilities.
        return stmt.on_conflict_do_update(
            index_elements=["type_id", "activity_id", "product_type_id"],
            set_={"quantity": stmt.excluded["quantity"]},
        )

    return _upsert_chunks(db, build, raw)


def update_activity_probabilities(db) -> int:
    """Invention success probabilities live in their OWN fuzzwork table
    (``industryActivityProbabilities``: typeID, activityID, productTypeID, probability),
    NOT in industryActivityProducts. Merge them onto the matching activity-product rows
    so ``eve_activity_products.probability`` is populated (else invention success chance
    reads 0). Must run AFTER update_activity_products so the rows exist."""
    raw = _dedup(_download_csv("industryActivityProbabilities"), "typeID", "activityID", "productTypeID")

    def build(batch):
        values = [
            {
                "type_id": _coerce(r, "typeID", int),
                "activity_id": _coerce(r, "activityID", int),
                "product_type_id": _coerce(r, "productTypeID", int),
                "probability": _coerce(r, "probability", float),
            }
            for r in batch
        ]
        stmt = pg_insert(EveActivityProduct).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["type_id", "activity_id", "product_type_id"],
            set_={"probability": stmt.excluded["probability"]},
        )

    return _upsert_chunks(db, build, raw)


def update_activity_skills(db) -> int:
    raw = _dedup(_download_csv("industryActivitySkills"), "typeID", "activityID", "skillID")

    def build(batch):
        values = [
            {
                "type_id": _coerce(r, "typeID", int),
                "activity_id": _coerce(r, "activityID", int),
                "skill_id": _coerce(r, "skillID", int),
                "level": _coerce(r, "level", int),
            }
            for r in batch
        ]
        stmt = pg_insert(EveActivitySkill).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["type_id", "activity_id", "skill_id"],
            set_={"level": stmt.excluded["level"]},
        )

    return _upsert_chunks(db, build, raw)


# Engineering-rig industry bonus attributes (see EveRigBonus docstring)
_RIG_ATTR_ME, _RIG_ATTR_TE, _RIG_ATTR_COST = 2594, 2593, 2595
_RIG_ATTR_HI, _RIG_ATTR_LOW, _RIG_ATTR_NULL = 2355, 2356, 2357
_RIG_ATTRS = {_RIG_ATTR_ME, _RIG_ATTR_TE, _RIG_ATTR_COST, _RIG_ATTR_HI, _RIG_ATTR_LOW, _RIG_ATTR_NULL}


def update_rig_bonuses(db) -> int:
    """Pivot engineering-rig bonuses out of dgmTypeAttributes into eve_rig_bonuses."""
    raw = _download_csv("dgmTypeAttributes")

    pivot: dict[int, dict[int, float]] = {}
    for r in raw:
        aid = _coerce(r, "attributeID", int)
        if aid not in _RIG_ATTRS:
            continue
        tid = _coerce(r, "typeID", int)
        if tid is None:
            continue
        val = _coerce(r, "valueFloat", float)
        if val is None:
            val = _coerce(r, "valueInt", float)
        pivot.setdefault(tid, {})[aid] = val

    # keep only types that actually carry a rig bonus (ME/TE/cost present)
    rig_ids = [t for t, a in pivot.items()
               if any(k in a for k in (_RIG_ATTR_ME, _RIG_ATTR_TE, _RIG_ATTR_COST))]

    groups = {}
    if rig_ids:
        for tid, gid in db.query(EveType.type_id, EveType.group_id).filter(EveType.type_id.in_(rig_ids)).all():
            groups[tid] = gid

    rows = []
    for tid in rig_ids:
        a = pivot[tid]
        rows.append({
            "type_id": tid,
            "group_id": groups.get(tid),
            "me_bonus": a.get(_RIG_ATTR_ME),
            "te_bonus": a.get(_RIG_ATTR_TE),
            "cost_bonus": a.get(_RIG_ATTR_COST),
            "hisec_mod": a.get(_RIG_ATTR_HI),
            "lowsec_mod": a.get(_RIG_ATTR_LOW),
            "nullsec_mod": a.get(_RIG_ATTR_NULL),
        })

    if not rows:
        return 0

    def build(batch):
        stmt = pg_insert(EveRigBonus).values(batch)
        return stmt.on_conflict_do_update(
            index_elements=["type_id"],
            set_={c: stmt.excluded[c] for c in
                  ("group_id", "me_bonus", "te_bonus", "cost_bonus",
                   "hisec_mod", "lowsec_mod", "nullsec_mod")},
        )

    return _upsert_chunks(db, build, rows)


def _reprocessing_yield_attr_ids() -> set[int]:
    """Resolve the dgm attribute id(s) carrying a reprocessing-yield bonus, by name.

    We don't hardcode a numeric attributeID (it has shifted between SDE releases and
    differs from the engineering ME/TE ids). Instead match dgmAttributeTypes names
    that mean "reprocessing yield" — robust across releases. Returns ``set()`` if the
    table can't be read, so the step degrades to importing no rigs rather than wrong
    ones.
    """
    try:
        attrs = _download_csv("dgmAttributeTypes")
    except Exception as exc:
        logger.warning("dgmAttributeTypes download failed: %s", exc)
        return set()
    ids: set[int] = set()
    for r in attrs:
        name = (r.get("attributeName") or "").lower()
        if "reprocess" in name and any(k in name for k in ("yield", "multiplier", "efficiency", "bonus")):
            aid = _coerce(r, "attributeID", int)
            if aid is not None:
                ids.add(aid)
    return ids


def update_reprocessing_rigs(db) -> int:
    """Pivot reprocessing-rig yield bonuses out of dgmTypeAttributes.

    Mirrors :func:`update_rig_bonuses`: pivot the (name-discovered) yield attribute
    plus the shared hi/low/null security modifiers, then keep only the Standup
    reprocessing rigs (type name contains "Reprocessing") so structures and ordinary
    items are excluded.
    """
    yield_attrs = _reprocessing_yield_attr_ids()
    if not yield_attrs:
        logger.warning("no reprocessing-yield attribute found in dgmAttributeTypes — skipping rigs")
        return 0
    wanted = yield_attrs | {_RIG_ATTR_HI, _RIG_ATTR_LOW, _RIG_ATTR_NULL}

    raw = _download_csv("dgmTypeAttributes")
    pivot: dict[int, dict[int, float]] = {}
    for r in raw:
        aid = _coerce(r, "attributeID", int)
        if aid not in wanted:
            continue
        tid = _coerce(r, "typeID", int)
        if tid is None:
            continue
        val = _coerce(r, "valueFloat", float)
        if val is None:
            val = _coerce(r, "valueInt", float)
        pivot.setdefault(tid, {})[aid] = val

    # candidate types carry a yield bonus; restrict to the reprocessing rigs by name
    cand_ids = [t for t, a in pivot.items() if any(k in a for k in yield_attrs)]
    if not cand_ids:
        return 0
    names = {tid: nm for tid, nm in
             db.query(EveType.type_id, EveType.type_name).filter(EveType.type_id.in_(cand_ids)).all()}
    groups = {tid: gid for tid, gid in
              db.query(EveType.type_id, EveType.group_id).filter(EveType.type_id.in_(cand_ids)).all()}

    rows = []
    for tid in cand_ids:
        if "reprocessing" not in (names.get(tid) or "").lower():
            continue
        a = pivot[tid]
        bonus = next((abs(a[k]) for k in yield_attrs if a.get(k)), None)
        rows.append({
            "type_id": tid,
            "group_id": groups.get(tid),
            "yield_bonus": bonus,
            "hisec_mod": a.get(_RIG_ATTR_HI),
            "lowsec_mod": a.get(_RIG_ATTR_LOW),
            "nullsec_mod": a.get(_RIG_ATTR_NULL),
        })

    if not rows:
        return 0

    def build(batch):
        stmt = pg_insert(EveReprocessingRig).values(batch)
        return stmt.on_conflict_do_update(
            index_elements=["type_id"],
            set_={c: stmt.excluded[c] for c in
                  ("group_id", "yield_bonus", "hisec_mod", "lowsec_mod", "nullsec_mod")},
        )

    return _upsert_chunks(db, build, rows)


def update_regions(db) -> int:
    raw = _download_csv("mapRegions")

    def build(batch):
        values = [
            {
                "region_id": _coerce(r, "regionID", int),
                "region_name": (r.get("regionName") or "")[:100],
                "faction_id": _coerce(r, "factionID", int),
                "x": _coerce(r, "x", float),
                "y": _coerce(r, "y", float),
                "z": _coerce(r, "z", float),
            }
            for r in batch
        ]
        stmt = pg_insert(EveRegion).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["region_id"],
            set_={c: stmt.excluded[c] for c in ("region_name", "faction_id", "x", "y", "z")},
        )

    return _upsert_chunks(db, build, raw)


def update_constellations(db) -> int:
    raw = _download_csv("mapConstellations")

    def build(batch):
        values = [
            {
                "constellation_id": _coerce(r, "constellationID", int),
                "region_id": _coerce(r, "regionID", int),
                "constellation_name": (r.get("constellationName") or "")[:100],
                "faction_id": _coerce(r, "factionID", int),
                "x": _coerce(r, "x", float),
                "y": _coerce(r, "y", float),
                "z": _coerce(r, "z", float),
            }
            for r in batch
        ]
        stmt = pg_insert(EveConstellation).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["constellation_id"],
            set_={c: stmt.excluded[c] for c in
                  ("region_id", "constellation_name", "faction_id", "x", "y", "z")},
        )

    return _upsert_chunks(db, build, raw)


def update_solar_systems(db) -> int:
    raw = _download_csv("mapSolarSystems")

    def build(batch):
        values = [
            {
                "solar_system_id": _coerce(r, "solarSystemID", int),
                "region_id": _coerce(r, "regionID", int),
                "constellation_id": _coerce(r, "constellationID", int),
                "solar_system_name": (r.get("solarSystemName") or "")[:100],
                "security": _coerce(r, "security", float),
                "security_class": (r.get("securityClass") or "")[:10] or None,
                "faction_id": _coerce(r, "factionID", int),
                "x": _coerce(r, "x", float),
                "y": _coerce(r, "y", float),
                "z": _coerce(r, "z", float),
            }
            for r in batch
        ]
        stmt = pg_insert(EveSolarSystem).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["solar_system_id"],
            set_={c: stmt.excluded[c] for c in (
                "region_id", "constellation_id", "solar_system_name",
                "security", "security_class", "faction_id", "x", "y", "z",
            )},
        )

    return _upsert_chunks(db, build, raw)


def update_planets(db) -> int:
    """Planets (and their radius/name/type) from mapDenormalize, filtered to groupID 7.

    mapDenormalize holds every celestial; we keep only planets so the PI tab can show a
    colony's planet name, physical radius and celestial type. The full file is large, so
    we filter in Python before upserting (~80k planet rows)."""
    raw = [r for r in _download_csv("mapDenormalize")
           if _coerce(r, "groupID", int) == _PLANET_GROUP_ID]

    def build(batch):
        values = [
            {
                "planet_id": _coerce(r, "itemID", int),
                "type_id": _coerce(r, "typeID", int),
                "solar_system_id": _coerce(r, "solarSystemID", int),
                "region_id": _coerce(r, "regionID", int),
                "planet_name": (r.get("itemName") or "")[:100] or None,
                "radius": _coerce(r, "radius", float),
                "celestial_index": _coerce(r, "celestialIndex", int),
            }
            for r in batch
        ]
        stmt = pg_insert(EvePlanet).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["planet_id"],
            set_={c: stmt.excluded[c] for c in (
                "type_id", "solar_system_id", "region_id",
                "planet_name", "radius", "celestial_index",
            )},
        )

    return _upsert_chunks(db, build, raw)


def update_stations(db) -> int:
    raw = _download_csv("staStations")

    def build(batch):
        values = [
            {
                "station_id": _coerce(r, "stationID", int),
                "station_name": (r.get("stationName") or "")[:200],
                "solar_system_id": _coerce(r, "solarSystemID", int),
                "constellation_id": _coerce(r, "constellationID", int),
                "region_id": _coerce(r, "regionID", int),
                "corporation_id": _coerce(r, "corporationID", int),
                "station_type_id": _coerce(r, "stationTypeID", int),
                "reprocessing_efficiency": _coerce(r, "reprocessingEfficiency", float),
                "reprocessing_stations_take": _coerce(r, "reprocessingStationsTake", float),
                "x": _coerce(r, "x", float),
                "y": _coerce(r, "y", float),
                "z": _coerce(r, "z", float),
            }
            for r in batch
        ]
        stmt = pg_insert(EveStation).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["station_id"],
            set_={c: stmt.excluded[c] for c in (
                "station_name", "solar_system_id", "constellation_id", "region_id",
                "corporation_id", "station_type_id",
                "reprocessing_efficiency", "reprocessing_stations_take",
                "x", "y", "z",
            )},
        )

    return _upsert_chunks(db, build, raw)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

STEPS: list[tuple[str, Any]] = [
    ("categories", update_categories),
    ("groups", update_groups),
    ("market_groups", update_market_groups),
    ("types", update_types),
    ("type_materials", update_type_materials),
    ("meta_types", update_meta_types),
    ("blueprints", update_blueprints),
    ("activity_times", update_activity_times),
    ("activity_materials", update_activity_materials),
    ("activity_products", update_activity_products),
    ("activity_probabilities", update_activity_probabilities),
    ("activity_skills", update_activity_skills),
    ("rig_bonuses", update_rig_bonuses),
    ("reprocessing_rigs", update_reprocessing_rigs),
    ("regions", update_regions),
    ("constellations", update_constellations),
    ("solar_systems", update_solar_systems),
    ("stations", update_stations),
    ("planets", update_planets),
]


# Steps whose target table was introduced after the original SDE schema. On an instance
# already at the current fuzzwork build, run_sde_update short-circuits and skips every step,
# so a newly-added table (e.g. eve_planets, mig 0036) would stay empty forever — its reads
# silently fall back ("Planet #<id>", null image). These steps self-heal: on a skipped sync
# they run when their table has no rows. Once populated they follow the normal build-bump path.
_BACKFILL_IF_EMPTY: list[tuple[str, Any, Any]] = [
    ("planets", update_planets, EvePlanet),
]


def _backfill_empty(db, summary: dict) -> list[str]:
    """Run any _BACKFILL_IF_EMPTY step whose table is empty. Returns the names run."""
    done: list[str] = []
    for step_name, step_fn, model in _BACKFILL_IF_EMPTY:
        try:
            if db.query(model).first() is not None:
                continue
        except Exception:  # table missing / not yet created — skip quietly
            continue
        try:
            count = step_fn(db)  # _upsert_chunks commits internally
            summary["steps"][step_name] = {"rows": count, "backfilled": True}
            done.append(step_name)
        except Exception as exc:
            logger.error("  backfill %-14s FAILED: %s", step_name, exc)
            summary["errors"].append(f"{step_name}: {exc}")
            db.rollback()
    return done


def run_sde_update(force: bool = False) -> dict:
    """
    Main entry point. Checks the fuzzwork build ID; skips if already current
    unless force=True. Returns a summary dict.
    """
    EveBase.metadata.create_all(bind=eve_engine)
    db = EveSessionLocal()
    summary: dict = {"skipped": False, "steps": {}, "errors": []}

    try:
        build_id, build_date = fetch_latest_build_info()
        logger.info("Latest fuzzwork build: %s (%s)", build_id, build_date)

        if not force and build_id and build_id == current_build_id(db):
            backfilled = _backfill_empty(db, summary)  # self-heal newly-added empty tables
            logger.info("SDE already up-to-date (build %s). Skipping%s.", build_id,
                        f" (backfilled {', '.join(backfilled)})" if backfilled else "")
            summary["skipped"] = True
            return summary

        for step_name, step_fn in STEPS:
            t0 = time.time()
            try:
                count = step_fn(db)
                elapsed = round(time.time() - t0, 1)
                logger.info("  %-22s %6d rows  %.1fs", step_name, count, elapsed)
                summary["steps"][step_name] = {"rows": count, "seconds": elapsed}
            except Exception as exc:
                logger.error("  %-22s FAILED: %s", step_name, exc)
                summary["errors"].append(f"{step_name}: {exc}")
                db.rollback()

        # persist meta
        meta = db.query(EveSdeMeta).filter(EveSdeMeta.id == 1).first()
        if meta is None:
            meta = EveSdeMeta(id=1)
            db.add(meta)
        meta.build_id = build_id
        meta.build_date = build_date
        meta.updated_at = utcnow()
        db.commit()

    except Exception as exc:
        logger.error("SDE update aborted: %s", exc)
        summary["errors"].append(str(exc))
    finally:
        db.close()

    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
    force = "--force" in sys.argv
    result = run_sde_update(force=force)
    if result["skipped"]:
        print("Already up-to-date.")
    elif result["errors"]:
        print("Completed with errors:", result["errors"])
    else:
        total = sum(s["rows"] for s in result["steps"].values())
        print(f"Done — {total:,} rows upserted across {len(result['steps'])} tables.")
