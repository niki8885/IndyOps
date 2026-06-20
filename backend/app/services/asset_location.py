"""Pure resolution of ESI asset location chains → a real terminus.

ESI hands back assets as a flat list of pointers, not a tree: each row's
``location_id`` names only its *immediate* container — a station, a solar
system, another item you own (a ship/container), or an Upwell structure you dock
in but don't own. The real place that holds a nested item (a module in a ship in
a citadel) is found by walking those pointers up until one stops pointing at
something in your own asset list.

This module is pure (no DB / no HTTP): callers pass the asset list as a map and
get back, per item, the terminus kind + id, then resolve names themselves
(stations / systems from the SDE, structures from the ESI structure cache).

See the "Resolving EVE ESI Asset Locations" reference for the full shape.
"""

_MAX_DEPTH = 10  # generous cycle/corruption guard; real nesting tops out at ~4–5

_SYSTEM_LO, _SYSTEM_HI = 30_000_000, 32_000_000
_STATION_LO, _STATION_HI = 60_000_000, 64_000_000


def _infer_kind(location_id):
    """Best-effort classification from the id alone (fallback when type missing)."""
    if location_id is None:
        return None
    if _SYSTEM_LO <= location_id < _SYSTEM_HI:
        return "system"
    if _STATION_LO <= location_id < _STATION_HI:
        return "station"
    return None  # ambiguous: item vs structure — needs the item-map membership test


def maybe_structure_id(location_id) -> bool:
    return location_id is not None and _infer_kind(location_id) is None


def resolve_root(location_id, location_type, items_by_id, depth=0):
    """
    Walk one asset's location chain to its root.

    ``items_by_id`` maps ``item_id -> {"location_id", "location_type"}`` for every
    row in the same asset list. Returns ``(kind, terminus_id)`` where ``kind`` is
    one of ``"station"``, ``"structure"``, ``"system"`` or ``None`` (unresolvable).
    """
    if location_id is None or depth > _MAX_DEPTH:
        return None, None

    lt = (location_type or "").lower()
    if not lt:
        lt = _infer_kind(location_id) or "item"

    if lt == "station":
        return "station", location_id
    if lt in ("solar_system", "system"):
        return "system", location_id
    if lt == "item":
        parent = items_by_id.get(location_id)
        if parent is not None:
            # the parent is a container / ship we own — climb one level
            return resolve_root(
                parent.get("location_id"), parent.get("location_type"),
                items_by_id, depth + 1,
            )
        # the parent isn't in our asset list → an Upwell structure we dock in
        return "structure", location_id
    return None, None  # 'other' / unknown


def terminus_ids(assets):
    """
    Resolve a whole asset list at once.

    ``assets`` is an iterable of objects/dicts exposing ``item_id``,
    ``location_id`` and ``location_type``. Returns ``(roots, by_kind)`` where
    ``roots`` maps ``item_id -> (kind, terminus_id)`` and ``by_kind`` maps each
    kind to the set of terminus ids needing a name lookup.
    """
    def _get(a, key):
        return a.get(key) if isinstance(a, dict) else getattr(a, key, None)

    items_by_id = {
        _get(a, "item_id"): {
            "location_id": _get(a, "location_id"),
            "location_type": _get(a, "location_type"),
        }
        for a in assets
    }

    roots = {}
    by_kind = {"station": set(), "structure": set(), "system": set()}
    for a in assets:
        kind, rid = resolve_root(_get(a, "location_id"), _get(a, "location_type"), items_by_id)
        roots[_get(a, "item_id")] = (kind, rid)
        if kind in by_kind and rid is not None:
            by_kind[kind].add(rid)
    return roots, by_kind
