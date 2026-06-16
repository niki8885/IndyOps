from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func

from app.core.database_eve import (
    EveType, EveActivityMaterial, EveActivityProduct, EveActivityTime, EveBlueprint,
    EveGroup, EveMetaType,
)

MANUFACTURING = 1
REACTION = 11
INDUSTRY_ACTIVITIES = (MANUFACTURING, REACTION)


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
            "type_id": r.material_type_id,
            "name": t.type_name if t else str(r.material_type_id),
            "base_qty": r.quantity,
            "volume": t.volume if t else None,
        })
    return result


def type_names(eve_db, type_ids: list[int]) -> dict[int, str]:
    """{type_id: type_name} for the given ids (single query)."""
    rows = eve_db.query(EveType.type_id, EveType.type_name).filter(
        EveType.type_id.in_(type_ids or [-1])).all()
    return {tid: name for tid, name in rows}


def type_groups(eve_db, type_ids: list[int]) -> dict[int, dict]:
    """{type_id: {"category_id", "group_name", "meta_group_id"}} (single query).

    Used to decide which engineering rigs apply to each node of a build tree —
    category/group for the size match, ``meta_group_id`` for the Basic/Advanced
    (Tech I vs Tech II/III) tech-level gate.
    """
    rows = (
        eve_db.query(EveType.type_id, EveGroup.category_id, EveGroup.group_name,
                     EveMetaType.meta_group_id)
        .outerjoin(EveGroup, EveType.group_id == EveGroup.group_id)
        .outerjoin(EveMetaType, EveType.type_id == EveMetaType.type_id)
        .filter(EveType.type_id.in_(type_ids or [-1]))
        .all()
    )
    return {tid: {"category_id": cid, "group_name": gname, "meta_group_id": mgid}
            for tid, cid, gname, mgid in rows}


def max_production_limit(eve_db, blueprint_type_id: int) -> Optional[int]:
    row = eve_db.query(EveBlueprint).filter(EveBlueprint.type_id == blueprint_type_id).first()
    return row.max_production_limit if row else None


def meta_group_for(eve_db, type_id: int) -> Optional[int]:
    """Tech level (meta group id) of one type, or None (treated as Tech I)."""
    row = eve_db.query(EveMetaType.meta_group_id).filter(EveMetaType.type_id == type_id).first()
    return row[0] if row else None


def type_volume(eve_db, type_id: int) -> Optional[float]:
    row = eve_db.query(EveType.volume).filter(EveType.type_id == type_id).first()
    return row[0] if row else None


def volumes(eve_db, type_ids: list[int]) -> dict[int, Optional[float]]:
    """{type_id: volume} for the given ids (single query)."""
    rows = eve_db.query(EveType.type_id, EveType.volume).filter(
        EveType.type_id.in_(type_ids or [-1])).all()
    return {tid: vol for tid, vol in rows}


def recipes_for_product(eve_db, product_type_id: int) -> list[dict]:
    """
    Every recipe that yields this product, across manufacturing (1) and
    reactions (11). A product may have more than one (alternative paths).
    """
    rows = (
        eve_db.query(EveActivityProduct)
        .filter(
            EveActivityProduct.product_type_id == product_type_id,
            EveActivityProduct.activity_id.in_(INDUSTRY_ACTIVITIES),
        )
        .all()
    )
    return [
        {"blueprint_type_id": r.type_id, "activity_id": r.activity_id, "qty_per_run": r.quantity}
        for r in rows
    ]


def product_for_blueprint(eve_db, blueprint_type_id: int) -> Optional[dict]:
    """What a blueprint makes (manufacturing or reaction), or None. The reverse of
    ``blueprint_for_product`` — used to key an owned blueprint to a chain node."""
    row = (
        eve_db.query(EveActivityProduct)
        .filter(
            EveActivityProduct.type_id == blueprint_type_id,
            EveActivityProduct.activity_id.in_(INDUSTRY_ACTIVITIES),
        )
        .first()
    )
    return None if row is None else {
        "product_type_id": row.product_type_id,
        "activity_id": row.activity_id,
        "qty_per_run": row.quantity,
    }


def types_by_name(eve_db, names: list[str]) -> dict[str, dict]:
    """{lower(name): {"type_id","name"}} for exact case-insensitive resolution
    (paste import). Skips blanks; one query."""
    lowered = sorted({n.strip().lower() for n in names if n and n.strip()})
    if not lowered:
        return {}
    rows = (
        eve_db.query(EveType.type_id, EveType.type_name)
        .filter(func.lower(EveType.type_name).in_(lowered))
        .all()
    )
    return {name.lower(): {"type_id": tid, "name": name} for tid, name in rows}


def bom_tree(eve_db, root_type_id: int, max_depth: int = 12) -> dict[int, dict]:
    """
    Walk the build-of-materials DAG from ``root_type_id`` down to raw leaves,
    spanning manufacturing (activity 1) and reactions (activity 11). Returns a
    flat ``{type_id: node}`` map where each node is::

        {"name": str, "category_id": int|None, "group_name": str|None,
         "meta_group_id": int|None,
         "recipes": [{"activity", "blueprint_type_id", "qty_per_run",
                      "base_time", "max_runs", "inputs": [{"type_id","qty"}]}]}

    Leaves (minerals, moon goo, PI, fuel blocks…) have ``recipes == []``. The
    walk is batched per depth level — a constant handful of queries per level
    regardless of how many materials a tier has (no N+1). Prices and facility
    bonuses are *not* read here; the adapter/router layer adds those to build a
    ``chain.ChainRequest``.
    """
    nodes: dict[int, dict] = {}
    frontier = {root_type_id}
    expanded: set[int] = set()
    depth = 0

    while frontier and depth < max_depth:
        depth += 1
        ids = list(frontier)

        prod_rows = (
            eve_db.query(EveActivityProduct)
            .filter(
                EveActivityProduct.product_type_id.in_(ids),
                EveActivityProduct.activity_id.in_(INDUSTRY_ACTIVITIES),
            )
            .all()
        )
        bp_index: dict[int, list] = defaultdict(list)  # product_type_id -> [(bp, act, qpr)]
        bp_ids: list[int] = []
        for r in prod_rows:
            bp_index[r.product_type_id].append((r.type_id, r.activity_id, r.quantity))
            bp_ids.append(r.type_id)

        mats_by_bp: dict[tuple[int, int], list] = defaultdict(list)
        time_by_bp: dict[tuple[int, int], int] = {}
        limit_by_bp: dict[int, Optional[int]] = {}
        if bp_ids:
            for r in (eve_db.query(EveActivityMaterial)
                    .filter(EveActivityMaterial.type_id.in_(bp_ids),
                            EveActivityMaterial.activity_id.in_(INDUSTRY_ACTIVITIES)).all()):
                mats_by_bp[(r.type_id, r.activity_id)].append((r.material_type_id, r.quantity))
            for r in (eve_db.query(EveActivityTime)
                    .filter(EveActivityTime.type_id.in_(bp_ids),
                            EveActivityTime.activity_id.in_(INDUSTRY_ACTIVITIES)).all()):
                time_by_bp[(r.type_id, r.activity_id)] = r.time
            for r in (eve_db.query(EveBlueprint)
                    .filter(EveBlueprint.type_id.in_(bp_ids)).all()):
                limit_by_bp[r.type_id] = r.max_production_limit

        next_frontier: set[int] = set()
        for tid in frontier:
            recipes = []
            for bp, act, qpr in bp_index.get(tid, []):
                inputs = mats_by_bp.get((bp, act), [])
                recipes.append({
                    "activity": act,
                    "blueprint_type_id": bp,
                    "qty_per_run": qpr or 1,
                    "base_time": time_by_bp.get((bp, act), 0),
                    "max_runs": limit_by_bp.get(bp),
                    "inputs": [{"type_id": m, "qty": q} for m, q in inputs],
                })
                for m, _ in inputs:
                    if m not in expanded:
                        next_frontier.add(m)
            nodes[tid] = {"name": None, "recipes": recipes}
            expanded.add(tid)
        frontier = {t for t in next_frontier if t not in expanded}

    for n in list(nodes.values()):
        for rc in n["recipes"]:
            for inp in rc["inputs"]:
                nodes.setdefault(inp["type_id"], {"name": None, "recipes": []})

    ids = list(nodes.keys())
    names = type_names(eve_db, ids)
    groups = type_groups(eve_db, ids)
    for tid, n in nodes.items():
        n["name"] = names.get(tid, str(tid))
        g = groups.get(tid) or {}
        n["category_id"] = g.get("category_id")
        n["group_name"] = g.get("group_name")
        n["meta_group_id"] = g.get("meta_group_id")
    return nodes
