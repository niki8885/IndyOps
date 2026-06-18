"""
EVE SDE repository against an in-memory SQLite database (no real Postgres).
Also pins the N+1 fix: materials() must run a constant number of queries.
"""
import pytest
from app.repositories import eve as eve_repo

MATS = [
    (34, 100, "Tritanium", 0.01),
    (35, 40, "Pyerite", 0.01),
    (36, 10, "Mexallon", 0.01),
]


def test_blueprint_for_product_returns_plain_ref(eve_session, seed_blueprint):
    ids = seed_blueprint(MATS)
    bp = eve_repo.blueprint_for_product(eve_session, ids["product_type_id"])
    assert bp is not None
    assert bp.blueprint_type_id == ids["bp_type_id"]
    assert bp.qty_per_run == 1
    assert type(bp).__name__ == "BlueprintRef"   # a dataclass, not an ORM row


def test_blueprint_missing_is_none(eve_session, seed_blueprint):
    seed_blueprint(MATS)
    assert eve_repo.blueprint_for_product(eve_session, 999_999) is None


def test_materials_enriched_with_name_and_volume(eve_session, seed_blueprint):
    ids = seed_blueprint(MATS)
    mats = eve_repo.materials(eve_session, ids["bp_type_id"])
    assert all(isinstance(m, dict) for m in mats)
    assert {m["type_id"] for m in mats} == {34, 35, 36}
    trit = next(m for m in mats if m["type_id"] == 34)
    assert (trit["name"], trit["base_qty"], trit["volume"]) == ("Tritanium", 100, 0.01)


def test_materials_no_n_plus_one(eve_session, seed_blueprint, query_counter):
    ids = seed_blueprint(MATS)              # 3 materials
    query_counter.reset()
    mats = eve_repo.materials(eve_session, ids["bp_type_id"])
    assert len(mats) == 3
    # constant 2 queries (activity_materials + one batched EveType.in_(...)),
    # not 1 + one-per-material.
    assert query_counter.count == 2


def test_lookup_helpers(eve_session, seed_blueprint):
    ids = seed_blueprint(MATS)
    bp = ids["bp_type_id"]
    assert eve_repo.base_time(eve_session, bp) == 600
    assert eve_repo.max_production_limit(eve_session, bp) == 10
    assert eve_repo.type_names(eve_session, [1000, 2000])[2000] == "Widget"
    assert eve_repo.type_volume(eve_session, 2000) == pytest.approx(2.5)
    assert eve_repo.volumes(eve_session, [34, 35]) == {34: 0.01, 35: 0.01}


def test_lookup_helpers_handle_empty(eve_session, seed_blueprint):
    seed_blueprint(MATS)
    assert eve_repo.base_time(eve_session, 999_999) == 0
    assert eve_repo.max_production_limit(eve_session, 999_999) is None
    assert eve_repo.type_volume(eve_session, 999_999) is None
    assert eve_repo.type_names(eve_session, []) == {}
