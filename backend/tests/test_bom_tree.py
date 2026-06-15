"""
bom_tree walks the full DAG across manufacturing (1) and reactions (11) and
stays batched per level (no N+1) — same SQLite-in-memory SDE as the other repo
tests.
"""
from app.core.database_eve import (
    EveActivityMaterial, EveActivityProduct, EveActivityTime, EveBlueprint, EveType,
)
from app.repositories import eve as eve_repo


def _seed_two_tier(s):
    """
    T2(2000) ← bp1000[act1]  : 4×COMP(3000) + 100×MIN(34)
    COMP(3000) ← bp1001[act11]: 2×MOON(4000)   (reaction, yields 10/run)
    MIN(34), MOON(4000) are leaves.
    """
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
    # 3 levels (hull / comp+min / moon) + one batched name lookup. Constant in the
    # number of materials per tier — adding a 4th input would NOT add a query.
    assert query_counter.count == 10


def test_recipes_for_product_lists_both_activities(eve_session):
    _seed_two_tier(eve_session)
    assert eve_repo.recipes_for_product(eve_session, 3000) == [
        {"blueprint_type_id": 1001, "activity_id": 11, "qty_per_run": 10}
    ]
    assert eve_repo.recipes_for_product(eve_session, 999) == []
