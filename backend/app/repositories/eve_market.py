from __future__ import annotations
from typing import Optional

from app.core.database_eve import (
    EveType, EveGroup, EveRegion, EveSolarSystem, EveStation, EveMarketGroup,
    EveMetaType,
)


def type_info(eve_db, type_id: int) -> Optional[dict]:
    """Name + group + market-group + volume for one type, or None if unknown."""
    row = (
        eve_db.query(EveType, EveGroup.group_name)
        .outerjoin(EveGroup, EveType.group_id == EveGroup.group_id)
        .filter(EveType.type_id == type_id)
        .first()
    )
    if not row:
        return None
    t, gname = row
    return {
        "type_id": t.type_id,
        "type_name": t.type_name,
        "group_id": t.group_id,
        "group_name": gname,
        "market_group_id": t.market_group_id,
        "volume": t.volume,
    }


def types_info(eve_db, type_ids: list[int]) -> dict[int, dict]:
    """{type_id: {type_id, type_name, group_id, group_name}} (single query)."""
    rows = (
        eve_db.query(EveType.type_id, EveType.type_name, EveType.group_id, EveGroup.group_name)
        .outerjoin(EveGroup, EveType.group_id == EveGroup.group_id)
        .filter(EveType.type_id.in_(type_ids or [-1]))
        .all()
    )
    return {tid: {"type_id": tid, "type_name": name, "group_id": gid, "group_name": gname}
            for tid, name, gid, gname in rows}


def types_market_meta(eve_db, type_ids: list[int]) -> dict[int, dict]:
    """{type_id: {type_name, category_id, group_id, meta_group_id, volume,
    market_group_id, published}}.

    Single EveType ⋈ EveGroup ⋈ EveMetaType query — supplies the category/group
    gates (trade allowlist + Drugs-by-group), the tech-level meta group (T1/T2/
    Faction filtering; NULL ⇒ Tech I) and the item volume (m³, for transport cost).
    Complements :func:`types_info`, which lacks volume/category.
    """
    rows = (
        eve_db.query(
            EveType.type_id, EveType.type_name, EveType.volume,
            EveType.market_group_id, EveType.published, EveType.group_id,
            EveGroup.category_id, EveMetaType.meta_group_id,
        )
        .outerjoin(EveGroup, EveType.group_id == EveGroup.group_id)
        .outerjoin(EveMetaType, EveType.type_id == EveMetaType.type_id)
        .filter(EveType.type_id.in_(type_ids or [-1]))
        .all()
    )
    return {
        tid: {
            "type_name": name,
            "volume": vol,
            "market_group_id": mgid,
            "published": bool(pub),
            "group_id": gid,
            "category_id": cat,
            "meta_group_id": meta,
        }
        for tid, name, vol, mgid, pub, gid, cat, meta in rows
    }


def type_ids_in_groups(eve_db, group_ids) -> list[int]:
    """Published, market-listed type_ids in the given inventory groups (e.g. the
    booster/"Drugs" group). Drives the haul scanner's extra universe inclusion."""
    ids = [int(g) for g in (group_ids or [])]
    if not ids:
        return []
    rows = (
        eve_db.query(EveType.type_id)
        .filter(
            EveType.group_id.in_(ids),
            EveType.published.is_(True),
            EveType.market_group_id.isnot(None),
        )
        .all()
    )
    return [tid for (tid,) in rows]


def region_name(eve_db, region_id: int) -> Optional[str]:
    row = eve_db.query(EveRegion.region_name).filter(EveRegion.region_id == region_id).first()
    return row[0] if row else None


def regions(eve_db, ids: list[int]) -> dict[int, str]:
    rows = eve_db.query(EveRegion.region_id, EveRegion.region_name).filter(
        EveRegion.region_id.in_(ids or [-1])).all()
    return {rid: name for rid, name in rows}


def stations(eve_db, ids: list[int]) -> dict[int, dict]:
    """{station_id: {name, system_id, region_id}} for NPC stations (single query)."""
    rows = (
        eve_db.query(EveStation.station_id, EveStation.station_name,
                     EveStation.solar_system_id, EveStation.region_id)
        .filter(EveStation.station_id.in_(ids or [-1]))
        .all()
    )
    return {sid: {"name": name, "system_id": ssid, "region_id": rid}
            for sid, name, ssid, rid in rows}


def systems(eve_db, ids: list[int]) -> dict[int, dict]:
    """{system_id: {name, security, region_id}} (single query)."""
    rows = (
        eve_db.query(EveSolarSystem.solar_system_id, EveSolarSystem.solar_system_name,
                     EveSolarSystem.security, EveSolarSystem.region_id)
        .filter(EveSolarSystem.solar_system_id.in_(ids or [-1]))
        .all()
    )
    return {ssid: {"name": name, "security": sec, "region_id": rid}
            for ssid, name, sec, rid in rows}


def market_group_path(eve_db, market_group_id: Optional[int], max_depth: int = 12) -> list[dict]:
    """Breadcrumb root→leaf, e.g. ``[Ships, Capital Ships, Freighters, Gallente]``.

    Walks ``parent_group_id`` upward from the item's market group, then reverses.
    """
    path: list[dict] = []
    cur = market_group_id
    seen: set[int] = set()
    while cur is not None and cur not in seen and len(path) < max_depth:
        seen.add(cur)
        row = (
            eve_db.query(EveMarketGroup.market_group_name, EveMarketGroup.parent_group_id)
            .filter(EveMarketGroup.market_group_id == cur)
            .first()
        )
        if not row:
            break
        name, parent = row
        path.append({"id": cur, "name": name})
        cur = parent
    path.reverse()
    return path


def group_members(eve_db, group_id: Optional[int], exclude_type_id: int, limit: int = 8) -> list[dict]:
    """Published, market-listed peers in the same inventory group (for correlation)."""
    if not group_id:
        return []
    rows = (
        eve_db.query(EveType.type_id, EveType.type_name)
        .filter(
            EveType.group_id == group_id,
            EveType.type_id != exclude_type_id,
            EveType.published.is_(True),
            EveType.market_group_id.isnot(None),
        )
        .order_by(EveType.type_name)
        .limit(limit)
        .all()
    )
    return [{"type_id": tid, "type_name": name} for tid, name in rows]
