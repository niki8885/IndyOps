"""
EVE Online SDE updater.

Downloads CSV exports from https://www.fuzzwork.co.uk/dump/latest/csv/
and upserts them into the eve_* tables defined in database_eve.py.

Activity IDs:
  1 = Manufacturing
  3 = Researching Time Efficiency
  4 = Researching Material Efficiency
  5 = Copying
  8 = Invention
  11 = Reactions
"""
import bz2
import csv
import datetime
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
    EveBlueprint,
    EveActivityTime,
    EveActivityMaterial,
    EveActivityProduct,
    EveActivitySkill,
    EveRegion,
    EveConstellation,
    EveSolarSystem,
    EveStation,
)

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


# ---------------------------------------------------------------------------
# Table updaters  (each returns row count upserted)
# ---------------------------------------------------------------------------

def _upsert_chunks(db, stmt_builder, rows: list[dict], chunk: int = CHUNK_SIZE) -> int:
    total = 0
    for i in range(0, len(rows), chunk):
        batch = rows[i : i + chunk]
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
                "category_id":   _coerce(r, "categoryID",   int),
                "category_name": r.get("categoryName", "")[:100],
                "icon_id":       _coerce(r, "iconID",       int),
                "published":     _bool(r.get("published")),
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
                "group_id":    _coerce(r, "groupID",    int),
                "category_id": _coerce(r, "categoryID", int),
                "group_name":  r.get("groupName", "")[:100],
                "icon_id":     _coerce(r, "iconID",     int),
                "published":   _bool(r.get("published")),
                "anchored":    _bool(r.get("anchored")),
                "anchorable":  _bool(r.get("anchorable")),
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
                "market_group_id":   _coerce(r, "marketGroupID",   int),
                "parent_group_id":   _coerce(r, "parentGroupID",   int),
                "market_group_name": r.get("marketGroupName", "")[:100],
                "description":       r.get("description") or None,
                "icon_id":           _coerce(r, "iconID",           int),
                "has_types":         _bool(r.get("hasTypes")),
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
                "type_id":         _coerce(r, "typeID",        int),
                "group_id":        _coerce(r, "groupID",       int),
                "type_name":       (r.get("typeName") or "")[:200],
                "description":     r.get("description") or None,
                "mass":            _coerce(r, "mass",          float),
                "volume":          _coerce(r, "volume",        float),
                "capacity":        _coerce(r, "capacity",      float),
                "portion_size":    _coerce(r, "portionSize",   int),
                "race_id":         _coerce(r, "raceID",        int),
                "base_price":      _coerce(r, "basePrice",     float),
                "published":       _bool(r.get("published")),
                "market_group_id": _coerce(r, "marketGroupID", int),
                "icon_id":         _coerce(r, "iconID",        int),
                "graphic_id":      _coerce(r, "graphicID",     int),
                "sound_id":        _coerce(r, "soundID",       int),
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


def update_blueprints(db) -> int:
    raw = _download_csv("industryBlueprints")

    def build(batch):
        values = [
            {
                "type_id":              _coerce(r, "typeID",             int),
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
    raw = _download_csv("industryActivity")

    def build(batch):
        values = [
            {
                "type_id":     _coerce(r, "typeID",     int),
                "activity_id": _coerce(r, "activityID", int),
                "time":        _coerce(r, "time",        int),
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
    raw = _download_csv("industryActivityMaterials")

    def build(batch):
        values = [
            {
                "type_id":          _coerce(r, "typeID",         int),
                "activity_id":      _coerce(r, "activityID",     int),
                "material_type_id": _coerce(r, "materialTypeID", int),
                "quantity":         _coerce(r, "quantity",        int),
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
    raw = _download_csv("industryActivityProducts")

    def build(batch):
        values = [
            {
                "type_id":         _coerce(r, "typeID",        int),
                "activity_id":     _coerce(r, "activityID",    int),
                "product_type_id": _coerce(r, "productTypeID", int),
                "quantity":        _coerce(r, "quantity",       int),
                "probability":     _coerce(r, "probability",    float),
            }
            for r in batch
        ]
        stmt = pg_insert(EveActivityProduct).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["type_id", "activity_id", "product_type_id"],
            set_={"quantity": stmt.excluded["quantity"], "probability": stmt.excluded["probability"]},
        )

    return _upsert_chunks(db, build, raw)


def update_activity_skills(db) -> int:
    raw = _download_csv("industryActivitySkills")

    def build(batch):
        values = [
            {
                "type_id":     _coerce(r, "typeID",     int),
                "activity_id": _coerce(r, "activityID", int),
                "skill_id":    _coerce(r, "skillID",    int),
                "level":       _coerce(r, "level",      int),
            }
            for r in batch
        ]
        stmt = pg_insert(EveActivitySkill).values(values)
        return stmt.on_conflict_do_update(
            index_elements=["type_id", "activity_id", "skill_id"],
            set_={"level": stmt.excluded["level"]},
        )

    return _upsert_chunks(db, build, raw)


def update_regions(db) -> int:
    raw = _download_csv("mapRegions")

    def build(batch):
        values = [
            {
                "region_id":   _coerce(r, "regionID",   int),
                "region_name": (r.get("regionName") or "")[:100],
                "faction_id":  _coerce(r, "factionID",  int),
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
                "constellation_id":   _coerce(r, "constellationID",   int),
                "region_id":          _coerce(r, "regionID",          int),
                "constellation_name": (r.get("constellationName") or "")[:100],
                "faction_id":         _coerce(r, "factionID",         int),
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
                "solar_system_id":   _coerce(r, "solarSystemID",   int),
                "region_id":         _coerce(r, "regionID",         int),
                "constellation_id":  _coerce(r, "constellationID",  int),
                "solar_system_name": (r.get("solarSystemName") or "")[:100],
                "security":          _coerce(r, "security",         float),
                "security_class":    (r.get("securityClass") or "")[:10] or None,
                "faction_id":        _coerce(r, "factionID",        int),
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


def update_stations(db) -> int:
    raw = _download_csv("staStations")

    def build(batch):
        values = [
            {
                "station_id":       _coerce(r, "stationID",       int),
                "station_name":     (r.get("stationName") or "")[:200],
                "solar_system_id":  _coerce(r, "solarSystemID",   int),
                "constellation_id": _coerce(r, "constellationID", int),
                "region_id":        _coerce(r, "regionID",        int),
                "corporation_id":   _coerce(r, "corporationID",   int),
                "station_type_id":  _coerce(r, "stationTypeID",   int),
                "reprocessing_efficiency":    _coerce(r, "reprocessingEfficiency",    float),
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
    ("categories",         update_categories),
    ("groups",             update_groups),
    ("market_groups",      update_market_groups),
    ("types",              update_types),
    ("blueprints",         update_blueprints),
    ("activity_times",     update_activity_times),
    ("activity_materials", update_activity_materials),
    ("activity_products",  update_activity_products),
    ("activity_skills",    update_activity_skills),
    ("regions",            update_regions),
    ("constellations",     update_constellations),
    ("solar_systems",      update_solar_systems),
    ("stations",           update_stations),
]


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
            logger.info("SDE already up-to-date (build %s). Skipping.", build_id)
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
        meta.build_id   = build_id
        meta.build_date = build_date
        meta.updated_at = datetime.datetime.utcnow()
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
