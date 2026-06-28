"""
Candidate-enumeration reads for the Reaction Planner: reaction_products /
manufactured_products_by_meta / industry_product_groups against the in-memory SDE.
"""
from app.core.database_eve import (
    EveActivityProduct, EveGroup, EveMetaType, EveType,
)
from app.repositories import eve as eve_repo


def _seed(s):
    # A composite reaction product (group 429 "Composite") + a fuel block (group 1136),
    # both reaction (activity 11). A T2 component (meta 2) made by manufacturing (act 1),
    # plus a T1 manufactured item (no meta row) that must NOT show up in the T2 sweep.
    s.add_all([
        EveGroup(group_id=429, category_id=4, group_name="Composite", published=True),
        EveGroup(group_id=1136, category_id=4, group_name="Fuel Block", published=True),
        EveGroup(group_id=334, category_id=17, group_name="Construction Components", published=True),
        # reaction products
        EveActivityProduct(type_id=46000, activity_id=11, product_type_id=16670, quantity=100),
        EveType(type_id=16670, type_name="Crystalline Carbonide", group_id=429, published=True),
        EveActivityProduct(type_id=46001, activity_id=11, product_type_id=4051, quantity=40),
        EveType(type_id=4051, type_name="Nitrogen Fuel Block", group_id=1136, published=True),
        # T2 component (meta 2) + its meta row
        EveActivityProduct(type_id=2700, activity_id=1, product_type_id=11539, quantity=1),
        EveType(type_id=11539, type_name="Magnetometric Sensor Cluster", group_id=334, published=True),
        EveMetaType(type_id=11539, parent_type_id=0, meta_group_id=2),
        # T1 manufactured item (no meta row) — excluded from the T2 sweep
        EveActivityProduct(type_id=2701, activity_id=1, product_type_id=12345, quantity=1),
        EveType(type_id=12345, type_name="Some T1 Thing", group_id=334, published=True),
        # an unpublished reaction product — excluded everywhere
        EveActivityProduct(type_id=46002, activity_id=11, product_type_id=99999, quantity=1),
        EveType(type_id=99999, type_name="Unpublished Goo", group_id=429, published=False),
    ])
    s.commit()


def test_reaction_products_lists_published_act11(eve_session):
    _seed(eve_session)
    rows = eve_repo.reaction_products(eve_session)
    by_id = {r["type_id"]: r for r in rows}
    assert set(by_id) == {16670, 4051}                         # published reaction products only
    assert by_id[16670]["group_name"] == "Composite"
    assert by_id[16670]["qty_per_run"] == 100
    assert by_id[16670]["blueprint_type_id"] == 46000
    assert by_id[4051]["group_name"] == "Fuel Block"
    assert 99999 not in by_id                                   # unpublished dropped


def test_reaction_products_group_filter(eve_session):
    _seed(eve_session)
    rows = eve_repo.reaction_products(eve_session, group_ids=[1136])
    assert [r["type_id"] for r in rows] == [4051]              # only the fuel block group


def test_manufactured_products_by_meta_gates_tech2(eve_session):
    _seed(eve_session)
    rows = eve_repo.manufactured_products_by_meta(eve_session, meta_group_id=2)
    ids = {r["type_id"] for r in rows}
    assert ids == {11539}                                      # the T2 component, not the T1 item
    assert rows[0]["meta_group_id"] == 2
    assert rows[0]["group_name"] == "Construction Components"


def test_industry_product_groups_counts(eve_session):
    _seed(eve_session)
    react_groups = {g["group_id"]: g for g in eve_repo.industry_product_groups(eve_session, 11)}
    assert react_groups[429]["count"] == 1 and react_groups[1136]["count"] == 1
    t2_groups = eve_repo.industry_product_groups(eve_session, 1, meta_group_id=2)
    assert [(g["group_id"], g["count"]) for g in t2_groups] == [(334, 1)]
