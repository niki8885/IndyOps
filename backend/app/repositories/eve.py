from __future__ import annotations
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func

from app.core.database_eve import (
    EveType, EveActivityMaterial, EveActivityProduct, EveActivityTime, EveActivitySkill,
    EveBlueprint, EveGroup, EveMetaType, EveTypeMaterial, EveReprocessingRig,
)

MANUFACTURING = 1
ME_RESEARCH = 3
TE_RESEARCH = 4
COPYING = 5
INVENTION = 8
REACTION = 11
INDUSTRY_ACTIVITIES = (MANUFACTURING, REACTION)


def max_runs(eve_db, blueprint_type_id: int) -> Optional[int]:
    """Blueprint max runs per copy (``eve_blueprints.max_production_limit``); None if unknown."""
    row = (
        eve_db.query(EveBlueprint.max_production_limit)
        .filter(EveBlueprint.type_id == blueprint_type_id)
        .first()
    )
    return int(row[0]) if row and row[0] is not None else None


def invention_products(eve_db, blueprint_type_id: int) -> list[dict]:
    """T2 blueprint outputs of a T1 blueprint's invention (activity 8): each is the
    invented ``product_type_id`` (a T2 BPC type), its base ``runs`` (SDE quantity)
    and base success ``probability``."""
    rows = (
        eve_db.query(EveActivityProduct)
        .filter(
            EveActivityProduct.type_id == blueprint_type_id,
            EveActivityProduct.activity_id == INVENTION,
        )
        .all()
    )
    return [
        {"product_type_id": r.product_type_id,
         "base_runs": int(r.quantity or 1),
         "probability": float(r.probability or 0.0)}
        for r in rows
    ]


def invention_skill_ids(eve_db, blueprint_type_id: int) -> list[int]:
    """Skill type_ids required for a blueprint's invention (one racial Encryption
    Methods skill + two datacore science skills)."""
    rows = (
        eve_db.query(EveActivitySkill.skill_id)
        .filter(
            EveActivitySkill.type_id == blueprint_type_id,
            EveActivitySkill.activity_id == INVENTION,
        )
        .all()
    )
    return [r[0] for r in rows]

# SDE classification constants (stable across releases).
CATEGORY_ASTEROID = 25   # invCategories: ore / compressed ore live here
GROUP_MINERAL = 18       # invGroups: the eight minerals + Morphite (and, since
                         # Equinox, the exotic refine products — see below)
GROUP_MOON_MATERIAL = 427  # invGroups: raw moon materials (moon-ore reprocess output)

# The eight classic minerals. Group 18 now ALSO holds the Equinox/Triglavian
# advanced refine products (Neo-Jadarite, Chromodynamic Tricarboxyls, Crystalline
# Raspite/Polycrase/Moissanite/Kangite, Eleutrium…), which are NOT what the
# acquisition calculators mean by "minerals". These ids are stable across releases.
CLASSIC_MINERAL_IDS = frozenset({
    34,     # Tritanium
    35,     # Pyerite
    36,     # Mexallon
    37,     # Isogen
    38,     # Nocxium
    39,     # Zydrine
    40,     # Megacyte
    11399,  # Morphite
})


@dataclass
class BlueprintRef:
    blueprint_type_id: int
    qty_per_run: int
    activity_id: int = 1   # 1 = manufacturing, 11 = reaction


def blueprint_for_product(eve_db, product_type_id: int) -> Optional[BlueprintRef]:
    rows = (
        eve_db.query(EveActivityProduct)
        .filter(
            EveActivityProduct.product_type_id == product_type_id,
            EveActivityProduct.activity_id.in_(INDUSTRY_ACTIVITIES),
        )
        .order_by(EveActivityProduct.activity_id)   # 1 (manufacturing) before 11 (reaction)
        .all()
    )
    if not rows:
        return None
    r = rows[0]
    return BlueprintRef(r.type_id, r.quantity, r.activity_id)


def base_time(eve_db, blueprint_type_id: int, activity_id: int = 1) -> int:
    """Base time (seconds per run) for the blueprint's activity, 0 if unknown."""
    row = (
        eve_db.query(EveActivityTime)
        .filter(
            EveActivityTime.type_id == blueprint_type_id,
            EveActivityTime.activity_id == activity_id,
        )
        .first()
    )
    return row.time if row else 0


def materials(eve_db, blueprint_type_id: int, activity_id: int = 1) -> list[dict]:
    """
    Base materials for a blueprint's activity (manufacturing or reaction), enriched
    with name + per-unit volume. One batched EveType lookup (was a query per material).
    """
    rows = (
        eve_db.query(EveActivityMaterial)
        .filter(
            EveActivityMaterial.type_id == blueprint_type_id,
            EveActivityMaterial.activity_id == activity_id,
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


def type_volumes(eve_db, type_ids: list[int]) -> dict[int, float]:
    """{type_id: packaged volume (m³)} for the given ids (single query). Missing → 0.0.
    Used to fold haul cost (ISK per m³) into the cheapest-source pricing."""
    rows = eve_db.query(EveType.type_id, EveType.volume).filter(
        EveType.type_id.in_(type_ids or [-1])).all()
    return {tid: float(vol) if vol is not None else 0.0 for tid, vol in rows}


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


def products_for_blueprints(eve_db, blueprint_type_ids: list[int]) -> dict[int, dict]:
    """Batched ``product_for_blueprint``: ``{blueprint_type_id: {product_type_id,
    activity_id, qty_per_run}}`` (one query, manufacturing preferred over reaction)."""
    ids = {t for t in blueprint_type_ids if t}
    if not ids:
        return {}
    rows = (
        eve_db.query(EveActivityProduct)
        .filter(
            EveActivityProduct.type_id.in_(ids),
            EveActivityProduct.activity_id.in_(INDUSTRY_ACTIVITIES),
        )
        .order_by(EveActivityProduct.activity_id)   # 1 (manufacturing) before 11 (reaction)
        .all()
    )
    out: dict[int, dict] = {}
    for r in rows:
        out.setdefault(r.type_id, {
            "product_type_id": r.product_type_id,
            "activity_id": r.activity_id,
            "qty_per_run": r.quantity,
        })
    return out


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


# ── Reprocessing / ore-acquisition reads ────────────────────────────────────

def mineral_catalog(eve_db) -> list[dict]:
    """The eight classic minerals (Tritanium … Megacyte + Morphite), with volume.

    Group 18 now also holds the Equinox/exotic refine products — those are excluded
    here; see :data:`CLASSIC_MINERAL_IDS`."""
    rows = (
        eve_db.query(EveType.type_id, EveType.type_name, EveType.volume)
        .filter(EveType.type_id.in_(CLASSIC_MINERAL_IDS))
        .order_by(EveType.type_id)
        .all()
    )
    return [{"type_id": tid, "name": name, "volume": vol} for tid, name, vol in rows]


def moon_material_catalog(eve_db) -> list[dict]:
    """Published raw moon materials (group 427) — the reprocess output of moon ore.

    Selectable as "needs" for the moon-ore acquisition comparison, mirroring the
    mineral flow (the eight ubiquitous/common/… moon goos plus the rare ones)."""
    rows = (
        eve_db.query(EveType.type_id, EveType.type_name, EveType.volume)
        .filter(EveType.group_id == GROUP_MOON_MATERIAL, EveType.published.is_(True))
        .order_by(EveType.type_name)
        .all()
    )
    return [{"type_id": tid, "name": name, "volume": vol} for tid, name, vol in rows]


def _is_dead_ore(name: Optional[str]) -> bool:
    """Event compression that can't be mined in normal space — only ``Batch
    Compressed …`` now. Post-patch the ``… <tier>-Grade`` ores are the *current* ore
    system (kept); the plain base ores are flagged ``legacy`` instead (see below)."""
    return (name or "").strip().lower().startswith("batch compressed")


_GRADE_SUFFIX_RE = re.compile(r"\s+\S+-grade$", re.IGNORECASE)


def _is_graded_ore(name: Optional[str]) -> bool:
    """True for the current graded ores (``Spodumain II-Grade``, ``Kangite X-Grade``…)."""
    return bool(_GRADE_SUFFIX_RE.search(name or ""))


def _grade_base_name(name: Optional[str]) -> Optional[str]:
    """Plain base name (lowercased) of a graded ore — ``Spodumain II-Grade`` →
    ``spodumain``, ``Compressed Spodumain II-Grade`` → ``compressed spodumain`` —
    else None. Used to flag the deprecating plain base ores as legacy."""
    m = _GRADE_SUFFIX_RE.search(name or "")
    return name[:m.start()].strip().lower() if m else None


def _exotic_material_ids(eve_db) -> set[int]:
    """Group-18 types that are NOT one of the eight classic minerals — i.e. the
    Equinox/Triglavian advanced refine products (Neo-Jadarite, Crystalline …)."""
    rows = (
        eve_db.query(EveType.type_id)
        .filter(EveType.group_id == GROUP_MINERAL, EveType.published.is_(True))
        .all()
    )
    return {tid for (tid,) in rows if tid not in CLASSIC_MINERAL_IDS}


def _exotic_ore_ids(eve_db, ore_ids: list[int]) -> set[int]:
    """Subset of ``ore_ids`` that reprocess into any exotic (non-classic) material —
    the Equinox/Triglavian ores (Kylixium, Bezdnacine, Raspite…). Data-driven, so it
    stays correct as CCP adds ores, without a name blocklist."""
    exo = _exotic_material_ids(eve_db)
    if not exo or not ore_ids:
        return set()
    rows = (
        eve_db.query(EveTypeMaterial.type_id)
        .filter(EveTypeMaterial.type_id.in_(ore_ids),
                EveTypeMaterial.material_type_id.in_(exo))
        .distinct()
        .all()
    )
    return {tid for (tid,) in rows}


def _ore_rows(eve_db, query, compressed: Optional[bool], include_exotic: bool) -> list[dict]:
    """Materialise an ore query into catalog dicts, applying the shared filters:
    always drop dead (``Batch Compressed``) ores, gate exotic ores on
    ``include_exotic``, and split raw vs compressed on ``compressed`` (True
    compressed-only / False raw-only / None both). Each row is tagged ``compressed``,
    ``exotic`` and ``legacy`` (a plain base ore whose graded variant exists — being
    phased out) for the UI."""
    raw = query.all()
    exotic_ids = _exotic_ore_ids(eve_db, [r[0] for r in raw])
    # plain base ores that have a graded sibling are "legacy" (deprecating post-patch)
    graded_bases = {_grade_base_name(name) for _, name, *_ in raw}
    graded_bases.discard(None)
    out = []
    for tid, name, vol, portion, gid, gname in raw:
        if _is_dead_ore(name):
            continue
        is_comp = (name or "").lower().startswith("compressed")
        if compressed is True and not is_comp:
            continue
        if compressed is False and is_comp:
            continue
        is_exotic = tid in exotic_ids
        if is_exotic and not include_exotic:
            continue
        is_legacy = (not _is_graded_ore(name)
                     and (name or "").strip().lower() in graded_bases)
        out.append({
            "type_id": tid, "name": name, "volume": vol,
            "portion_size": portion or 1, "group_id": gid,
            "group_name": gname, "compressed": is_comp,
            "exotic": is_exotic, "legacy": is_legacy,
        })
    return out


def ore_catalog(eve_db, compressed: Optional[bool] = None,
                include_exotic: bool = False) -> list[dict]:
    """Published ore types (Asteroid category) that have a reprocessing yield.

    ``compressed``: True → only "Compressed …" variants, False → only raw ore,
    None → both. ``include_exotic`` gates the Equinox/Triglavian exotic ores. Dead
    ``Batch Compressed`` ores are always excluded; graded ores are kept and plain base
    ores tagged ``legacy``. ``portion_size`` is the reprocess batch size."""
    q = (
        eve_db.query(EveType.type_id, EveType.type_name, EveType.volume,
                     EveType.portion_size, EveType.group_id, EveGroup.group_name)
        .join(EveGroup, EveType.group_id == EveGroup.group_id)
        .filter(EveGroup.category_id == CATEGORY_ASTEROID, EveType.published.is_(True))
        .filter(EveType.type_id.in_(eve_db.query(EveTypeMaterial.type_id).distinct()))
        .order_by(EveType.type_name)
    )
    return _ore_rows(eve_db, q, compressed, include_exotic)


def ores_yielding(eve_db, mineral_type_ids: list[int],
                  compressed: Optional[bool] = None,
                  include_exotic: bool = False) -> list[dict]:
    """Ore types whose reprocessing yield includes any of ``mineral_type_ids``.

    Works for any need (classic minerals *or* moon materials): a moon material in
    ``mineral_type_ids`` brings in the moon ores that yield it. Dead ``Batch
    Compressed`` ores are always dropped; exotic ores are gated on ``include_exotic``;
    plain base ores with a graded variant are tagged ``legacy``."""
    if not mineral_type_ids:
        return []
    ore_ids = [
        r[0] for r in eve_db.query(EveTypeMaterial.type_id)
        .filter(EveTypeMaterial.material_type_id.in_(mineral_type_ids))
        .distinct().all()
    ]
    if not ore_ids:
        return []
    q = (
        eve_db.query(EveType.type_id, EveType.type_name, EveType.volume,
                     EveType.portion_size, EveType.group_id, EveGroup.group_name)
        .join(EveGroup, EveType.group_id == EveGroup.group_id)
        .filter(EveGroup.category_id == CATEGORY_ASTEROID, EveType.published.is_(True))
        .filter(EveType.type_id.in_(ore_ids))
        .order_by(EveType.type_name)
    )
    return _ore_rows(eve_db, q, compressed, include_exotic)


def reprocessing_yields(eve_db, type_ids: list[int]) -> dict[int, dict]:
    """{type_id: {"portion_size", "materials": [{type_id, name, quantity}]}}.

    ``materials`` is the perfect (100%) mineral output for one ``portion_size`` batch.
    Batched: one EveTypeMaterial query + one name lookup (no N+1).
    """
    if not type_ids:
        return {}
    rows = (
        eve_db.query(EveTypeMaterial)
        .filter(EveTypeMaterial.type_id.in_(type_ids))
        .all()
    )
    portions = {
        tid: (ps or 1)
        for tid, ps in eve_db.query(EveType.type_id, EveType.portion_size)
        .filter(EveType.type_id.in_(type_ids)).all()
    }
    mat_ids = list({r.material_type_id for r in rows})
    names = type_names(eve_db, mat_ids)
    out: dict[int, dict] = {tid: {"portion_size": portions.get(tid, 1), "materials": []}
                            for tid in type_ids}
    for r in rows:
        out.setdefault(r.type_id, {"portion_size": portions.get(r.type_id, 1), "materials": []})
        out[r.type_id]["materials"].append({
            "type_id": r.material_type_id,
            "name": names.get(r.material_type_id, str(r.material_type_id)),
            "quantity": r.quantity,
        })
    return out


# Harvestable gas is identified by stable name patterns (category/group ids have
# shifted between SDE releases). Fullerene gas + booster gas (Cyto/Mykoserocin).
GAS_NAME_PATTERNS = ("Fullerite-%", "% Cytoserocin", "% Mykoserocin")


def gas_catalog(eve_db) -> list[dict]:
    """Harvestable gases paired with their compressed variant.

    ``units_per_compressed`` = regular units one compressed unit decompresses into
    (from the compressed type's invTypeMaterials → base gas). None if the SDE has no
    such row, in which case the UI offers only the regular form for that gas.
    """
    from sqlalchemy import or_
    conds = [EveType.type_name.ilike(p) for p in GAS_NAME_PATTERNS]
    rows = (
        eve_db.query(EveType.type_id, EveType.type_name, EveType.volume)
        .filter(or_(*conds), EveType.published.is_(True))
        .order_by(EveType.type_name)
        .all()
    )
    regs = [(tid, name, vol) for tid, name, vol in rows
            if not (name or "").lower().startswith("compressed")]

    # compressed variants, matched by "Compressed <name>"
    comp_lookup = {f"compressed {name.lower()}": tid for tid, name, _ in regs}
    comp_rows = (
        eve_db.query(EveType.type_id, EveType.type_name, EveType.volume)
        .filter(func.lower(EveType.type_name).in_(list(comp_lookup) or ["-"]))
        .all()
    )
    comp_by_name = {name.lower(): (tid, name, vol) for tid, name, vol in comp_rows}
    yld = reprocessing_yields(eve_db, [tid for tid, _, _ in comp_rows])

    out = []
    for tid, name, vol in regs:
        c = comp_by_name.get(f"compressed {name.lower()}")
        entry = {"reg_type_id": tid, "reg_name": name, "reg_volume": vol,
                 "comp_type_id": None, "comp_name": None, "comp_volume": None,
                 "units_per_compressed": None}
        if c:
            cid, cname, cvol = c
            entry.update(comp_type_id=cid, comp_name=cname, comp_volume=cvol)
            y = yld.get(cid)
            if y and y["materials"]:
                base = next((m for m in y["materials"] if m["type_id"] == tid), y["materials"][0])
                ps = y["portion_size"] or 1
                entry["units_per_compressed"] = (base["quantity"] or 0) / ps
        out.append(entry)
    return out


def reprocessing_rigs(eve_db) -> list[dict]:
    """All structure reprocessing-yield rigs, with name + yield bonus + sec modifiers."""
    rows = (
        eve_db.query(EveReprocessingRig, EveType.type_name)
        .outerjoin(EveType, EveReprocessingRig.type_id == EveType.type_id)
        .order_by(EveType.type_name)
        .all()
    )
    return [
        {
            "type_id": rb.type_id,
            "name": name or str(rb.type_id),
            "group_id": rb.group_id,
            "yield_bonus": rb.yield_bonus,
            "hisec_mod": rb.hisec_mod,
            "lowsec_mod": rb.lowsec_mod,
            "nullsec_mod": rb.nullsec_mod,
        }
        for rb, name in rows
    ]


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
