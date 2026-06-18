"""
Static reference data for the trade optimizer (mirrors ``indices_data.py``).

The five main NPC trade hubs, the approximate gate-jump distances between them
(used to estimate per-unit transport cost in the cross-hub pipeline), and the
human-readable names for the market-category allowlist.

``buy_hub`` / ``sell_hub`` in the candidate tables are station_ids, so the jump
table is keyed by station_id pairs. Jump counts are best-effort highsec
shortest-route approximations — they only feed a rough transport cost and are
fully overridable via ``config.TRADE_ISK_PER_JUMP_M3``; refine via ESI ``/route/``
later if needed.
"""

# name -> {region_id, station_id, system_id}
HUBS: dict[str, dict[str, int]] = {
    "Jita":    {"region_id": 10000002, "station_id": 60003760, "system_id": 30000142},
    "Amarr":   {"region_id": 10000043, "station_id": 60008494, "system_id": 30002187},
    "Dodixie": {"region_id": 10000032, "station_id": 60011866, "system_id": 30002659},
    "Rens":    {"region_id": 10000030, "station_id": 60004588, "system_id": 30002510},
    "Hek":     {"region_id": 10000042, "station_id": 60005686, "system_id": 30002053},
}

HUB_NAMES = list(HUBS.keys())
HUB_STATION_IDS = {name: h["station_id"] for name, h in HUBS.items()}
HUB_REGION_IDS = {name: h["region_id"] for name, h in HUBS.items()}
# reverse lookups for collectors
STATION_TO_HUB = {h["station_id"]: name for name, h in HUBS.items()}
REGION_TO_HUB = {h["region_id"]: name for name, h in HUBS.items()}

# Symmetric gate-jump distances keyed by an (unordered) pair of station_ids.
_JUMPS_SYM: dict[frozenset, int] = {
    frozenset({60003760, 60008494}): 9,    # Jita  – Amarr
    frozenset({60003760, 60011866}): 15,   # Jita  – Dodixie
    frozenset({60003760, 60004588}): 23,   # Jita  – Rens
    frozenset({60003760, 60005686}): 19,   # Jita  – Hek
    frozenset({60008494, 60011866}): 14,   # Amarr – Dodixie
    frozenset({60008494, 60004588}): 18,   # Amarr – Rens
    frozenset({60008494, 60005686}): 16,   # Amarr – Hek
    frozenset({60011866, 60004588}): 13,   # Dodixie – Rens
    frozenset({60011866, 60005686}): 11,   # Dodixie – Hek
    frozenset({60004588, 60005686}): 6,    # Rens  – Hek
}


def jumps_between(station_a: int, station_b: int) -> int:
    """Approximate gate jumps between two hub stations (0 if same)."""
    if station_a == station_b:
        return 0
    return _JUMPS_SYM.get(frozenset({station_a, station_b}), 0)


# SDE invCategories that may become candidates (see config.TRADE_CATEGORY_ALLOWLIST)
CATEGORY_NAMES = {
    6: "Ship",
    7: "Module",
    8: "Charge",
    18: "Drone",
    87: "Fighter",
}
