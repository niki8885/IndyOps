
from app.core.database_eve import (
    EveActivityMaterial, EveActivityProduct, EveActivityTime, EveBlueprint, EveType,
    EveMetaType,
)
from app.repositories import eve as eve_repo


def _seed_two_tier(s):
    s.add_all([
        EveActivityProduct(type_id=1000, activity_id=1, product_type_id=2000, quantity=1),
        EveActivityProduct(type_id=1001, activity_id=11, product_type_id=3000, quantity=10),
        EveActivityMaterial(type_id=1000, activity_id=1, material_type_id=3000, quantity=4),
        EveActivityMaterial(type_id=1000, activity_id=1, material_type_id=34, quantity=100),
        EveActivityMaterial(type_id=1001, activity_id=11, material_type_id=4000, quantity=2),
        EveActivityTime(type_id=1000, activity_id=1, time=600),
        EveActivityTime(type_id=1001, activity_id=11, time=3600),
        EveBlueprint(type_id=1000, max_production_limit=10),
        EveBlueprint(type_id=1001, max_production_limit=100),
        EveType(type_id=2000, type_name="T2 Hull"),
        EveType(type_id=3000, type_name="Composite Component"),
        EveType(type_id=34, type_name="Tritanium"),
        EveType(type_id=4000, type_name="Moon Goo"),
    ])
    s.commit()


def test_bom_tree_spans_manufacturing_and_reactions(eve_session):
    _seed_two_tier(eve_session)
    tree = eve_repo.bom_tree(eve_session, 2000)

    assert set(tree) == {2000, 3000, 34, 4000}

    hull = tree[2000]["recipes"][0]
    assert hull["activity"] == 1 and hull["max_runs"] == 10 and hull["base_time"] == 600
    assert {i["type_id"]: i["qty"] for i in hull["inputs"]} == {3000: 4, 34: 100}

    comp = tree[3000]["recipes"][0]
    assert comp["activity"] == 11 and comp["qty_per_run"] == 10 and comp["base_time"] == 3600
    assert {i["type_id"]: i["qty"] for i in comp["inputs"]} == {4000: 2}

    assert tree[34]["recipes"] == [] and tree[4000]["recipes"] == []   # leaves
    assert tree[2000]["name"] == "T2 Hull" and tree[4000]["name"] == "Moon Goo"


def test_bom_tree_is_batched_per_level(eve_session, query_counter):
    _seed_two_tier(eve_session)
    query_counter.reset()
    eve_repo.bom_tree(eve_session, 2000)
    # 3 levels (hull / comp+min / moon) + batched name + group lookups. Constant in
    # the number of materials per tier — adding a 4th input would NOT add a query.
    assert query_counter.count == 11


def test_bom_tree_surfaces_meta_group(eve_session):
    """Each node carries its tech level (meta_group_id); nodes with no invMetaTypes
    row come back None (treated as Tech I by the rig gate)."""
    _seed_two_tier(eve_session)
    eve_session.add(EveMetaType(type_id=2000, meta_group_id=2))   # T2 hull
    eve_session.commit()
    tree = eve_repo.bom_tree(eve_session, 2000)
    assert tree[2000]["meta_group_id"] == 2
    assert tree[3000]["meta_group_id"] is None
    assert eve_repo.meta_group_for(eve_session, 2000) == 2
    assert eve_repo.meta_group_for(eve_session, 3000) is None


def test_recipes_for_product_lists_both_activities(eve_session):
    _seed_two_tier(eve_session)
    assert eve_repo.recipes_for_product(eve_session, 3000) == [
        {"blueprint_type_id": 1001, "activity_id": 11, "qty_per_run": 10}
    ]
    assert eve_repo.recipes_for_product(eve_session, 999) == []


def test_product_for_blueprint_reverse_lookup(eve_session):
    _seed_two_tier(eve_session)
    assert eve_repo.product_for_blueprint(eve_session, 1000) == {
        "product_type_id": 2000, "activity_id": 1, "qty_per_run": 1}
    assert eve_repo.product_for_blueprint(eve_session, 1001)["activity_id"] == 11
    assert eve_repo.product_for_blueprint(eve_session, 999) is None


def test_types_by_name_exact_case_insensitive(eve_session):
    _seed_two_tier(eve_session)
    out = eve_repo.types_by_name(eve_session, ["t2 hull", "Moon Goo", "nope"])
    assert out["t2 hull"]["type_id"] == 2000
    assert out["moon goo"]["type_id"] == 4000
    assert "nope" not in out
