"""Tests for the ESI asset-location chain walker (services/asset_location)."""
from app.services import asset_location as al


def _map(assets):
    return {
        a["item_id"]: {"location_id": a["location_id"], "location_type": a["location_type"]}
        for a in assets
    }


def test_direct_station():
    items = _map([{"item_id": 1, "location_id": 60003760, "location_type": "station"}])
    assert al.resolve_root(60003760, "station", items) == ("station", 60003760)


def test_direct_solar_system():
    items = _map([{"item_id": 1, "location_id": 30000142, "location_type": "solar_system"}])
    assert al.resolve_root(30000142, "solar_system", items) == ("system", 30000142)


def test_module_in_ship_in_structure():
    # a module fitted to a ship that sits in an Upwell structure we don't own
    struct = 1_000_000_000_001
    assets = [
        {"item_id": 1, "location_id": 2, "location_type": "item"},       # module in ship
        {"item_id": 2, "location_id": struct, "location_type": "item"},  # ship in structure
    ]
    items = _map(assets)
    # both the module and the ship resolve to the same structure terminus
    assert al.resolve_root(2, "item", items) == ("structure", struct)
    assert al.resolve_root(1, "item", items) == ("structure", struct)


def test_nested_container_in_npc_station():
    assets = [
        {"item_id": 10, "location_id": 60003760, "location_type": "station"},  # container in station
        {"item_id": 11, "location_id": 10, "location_type": "item"},           # item in container
    ]
    items = _map(assets)
    assert al.resolve_root(10, "item", items) == ("station", 60003760)


def test_unknown_type_returns_none():
    assert al.resolve_root(123, "other", {}) == (None, None)


def test_missing_type_inferred_from_id_range():
    # location_type absent → infer station / system from the id magnitude
    assert al.resolve_root(60003760, None, {}) == ("station", 60003760)
    assert al.resolve_root(30000142, None, {}) == ("system", 30000142)


def test_cycle_guard_terminates():
    # corrupt data: two items point at each other — must not recurse forever
    assets = [
        {"item_id": 1, "location_id": 2, "location_type": "item"},
        {"item_id": 2, "location_id": 1, "location_type": "item"},
    ]
    items = _map(assets)
    assert al.resolve_root(1, "item", items) == (None, None)


def test_terminus_ids_groups_by_kind():
    struct = 1_000_000_000_001
    assets = [
        {"item_id": 1, "location_id": 60003760, "location_type": "station"},
        {"item_id": 2, "location_id": struct, "location_type": "item"},
        {"item_id": 3, "location_id": 2, "location_type": "item"},
        {"item_id": 4, "location_id": 30000142, "location_type": "solar_system"},
    ]
    roots, by_kind = al.terminus_ids(assets)
    assert roots[1] == ("station", 60003760)
    assert roots[3] == ("structure", struct)
    assert by_kind["station"] == {60003760}
    assert by_kind["structure"] == {struct}
    assert by_kind["system"] == {30000142}
