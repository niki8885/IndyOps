"""
Read-only EVE SDE access.

Functions return plain values / dicts / dataclasses — never ORM rows — so the
service layer and routers stay decoupled from SQLAlchemy. The per-material and
per-rig EveType lookups that used to run one query per row (N+1) are batched
here with a single ``type_id.in_(...)`` + map.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.database_eve import (
    EveType, EveActivityMaterial, EveActivityProduct, EveActivityTime, EveBlueprint,
)


@dataclass
class BlueprintRef:
    blueprint_type_id: int
    qty_per_run: int


def blueprint_for_product(eve_db, product_type_id: int) -> Optional[BlueprintRef]:
    """Manufacturing blueprint (activity 1) that produces this product, or None."""
    row = (
        eve_db.query(EveActivityProduct)
        .filter(
            EveActivityProduct.product_type_id == product_type_id,
            EveActivityProduct.activity_id == 1,
        )
        .first()
    )
    return BlueprintRef(row.type_id, row.quantity) if row else None


def base_time(eve_db, blueprint_type_id: int) -> int:
    """Base manufacturing time (seconds per run), 0 if unknown."""
    row = (
        eve_db.query(EveActivityTime)
        .filter(
            EveActivityTime.type_id == blueprint_type_id,
            EveActivityTime.activity_id == 1,
        )
        .first()
    )
    return row.time if row else 0


def materials(eve_db, blueprint_type_id: int) -> list[dict]:
    """
    Base materials for a blueprint, enriched with name + per-unit volume.
    One batched EveType lookup (was a query per material — N+1).
    """
    rows = (
        eve_db.query(EveActivityMaterial)
        .filter(
            EveActivityMaterial.type_id == blueprint_type_id,
            EveActivityMaterial.activity_id == 1,
        )
        .all()
    )
    type_ids = [r.material_type_id for r in rows]
    types = {
        t.type_id: t
        for t in eve_db.query(EveType).filter(EveType.type_id.in_(type_ids or [-1])).all()
    }
    result = []
    for r in rows:
        t = types.get(r.material_type_id)
        result.append({
            "type_id":  r.material_type_id,
            "name":     t.type_name if t else str(r.material_type_id),
            "base_qty": r.quantity,
            "volume":   t.volume if t else None,
        })
    return result


def type_names(eve_db, type_ids: list[int]) -> dict[int, str]:
    """{type_id: type_name} for the given ids (single query)."""
    rows = eve_db.query(EveType.type_id, EveType.type_name).filter(
        EveType.type_id.in_(type_ids or [-1])).all()
    return {tid: name for tid, name in rows}


def max_production_limit(eve_db, blueprint_type_id: int) -> Optional[int]:
    row = eve_db.query(EveBlueprint).filter(EveBlueprint.type_id == blueprint_type_id).first()
    return row.max_production_limit if row else None


def type_volume(eve_db, type_id: int) -> Optional[float]:
    row = eve_db.query(EveType.volume).filter(EveType.type_id == type_id).first()
    return row[0] if row else None


def volumes(eve_db, type_ids: list[int]) -> dict[int, Optional[float]]:
    """{type_id: volume} for the given ids (single query)."""
    rows = eve_db.query(EveType.type_id, EveType.volume).filter(
        EveType.type_id.in_(type_ids or [-1])).all()
    return {tid: vol for tid, vol in rows}
