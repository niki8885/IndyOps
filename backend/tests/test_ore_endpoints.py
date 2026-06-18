"""
Ore Acquisition & Refining router (IO-13) endpoint tests.

Driven the project's no-HTTP way: the route functions are imported and called
directly with seeded in-memory SQLite sessions and a SimpleNamespace user, while
*every* market/ESI seam on the router module is monkeypatched so no network or
ThreadPoolExecutor work ever hits the wire. The router's own logic
(``_resolve_sources``, ``_region_two_sided``, ``_cj_two_sided``, ``_cost_per_m3``,
``_volatility_alerts`` …) still runs, so it is exercised for coverage.

SDE seeding mirrors tests/test_ore_basket.py / test_refining.py + the ore-domain
repository reads in app/repositories/eve.py.
"""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.ore_router as orr
from app.core.database import Base, LinkedCharacter, EsiSkill
from app.core.database_eve import (
    EveBase, EveType, EveGroup, EveTypeMaterial, EveReprocessingRig, EveSolarSystem,
)

USER = SimpleNamespace(id=1)
CID = 99

# type ids ────────────────────────────────────────────────────────────────────
TRIT, PYE = 34, 35                 # classic minerals (group 18)
VELD, CVELD = 1230, 28432          # raw + compressed Veldspar (asteroid category 25)
GAS_REG, GAS_COMP = 25268, 62454   # Fullerite-C50 + its compressed variant
RIG = 46640                        # a reprocessing rig
JITA_SYS = 30000142
CJ_SYS = 30004759
TARGET_SYS = 30000144              # Perimeter (the delivery target)


def run(coro):
    return asyncio.run(coro)


def _mem_db(base):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


@pytest.fixture
def app_db():
    session, engine = _mem_db(Base)
    yield session
    session.close(); engine.dispose()


@pytest.fixture
def eve_db():
    session, engine = _mem_db(EveBase)
    _seed_sde(session)
    yield session
    session.close(); engine.dispose()


def _seed_sde(db):
    """Minerals, ores (raw + compressed Veldspar yielding Trit+Pyerite), gas pair,
    a reprocessing rig, and solar systems."""
    db.add_all([
        # groups: minerals (18), asteroid ore group in category 25, gas group
        EveGroup(group_id=18, category_id=4, group_name="Mineral", published=True),
        EveGroup(group_id=450, category_id=25, group_name="Veldspar", published=True),
        EveGroup(group_id=711, category_id=25, group_name="Fullerite-C50", published=True),
        # minerals
        EveType(type_id=TRIT, type_name="Tritanium", group_id=18, volume=0.01, published=True),
        EveType(type_id=PYE, type_name="Pyerite", group_id=18, volume=0.01, published=True),
        # raw + compressed ore (portion 100), both reprocessing to Trit + Pyerite
        EveType(type_id=VELD, type_name="Veldspar", group_id=450, volume=0.1,
                portion_size=100, published=True),
        EveType(type_id=CVELD, type_name="Compressed Veldspar", group_id=450, volume=0.15,
                portion_size=100, published=True),
        EveTypeMaterial(type_id=VELD, material_type_id=TRIT, quantity=400),
        EveTypeMaterial(type_id=VELD, material_type_id=PYE, quantity=200),
        EveTypeMaterial(type_id=CVELD, material_type_id=TRIT, quantity=400),
        EveTypeMaterial(type_id=CVELD, material_type_id=PYE, quantity=200),
        # gas pair: regular + compressed (compressed decompresses into 100 regular)
        EveType(type_id=GAS_REG, type_name="Fullerite-C50", group_id=711, volume=1.0,
                portion_size=1, published=True),
        EveType(type_id=GAS_COMP, type_name="Compressed Fullerite-C50", group_id=711,
                volume=0.05, portion_size=1, published=True),
        EveTypeMaterial(type_id=GAS_COMP, material_type_id=GAS_REG, quantity=100),
        # a reprocessing-yield rig
        EveReprocessingRig(type_id=RIG, group_id=1, yield_bonus=2.0,
                           hisec_mod=1.0, lowsec_mod=1.9, nullsec_mod=2.1),
        EveType(type_id=RIG, type_name="Standup M-Set Reprocessing", group_id=1, published=True),
        # solar systems (hubs + target). Jita/Perimeter hi-sec, C-J null-sec.
        EveSolarSystem(solar_system_id=JITA_SYS, solar_system_name="Jita", region_id=10000002,
                       security=0.95, x=0.0, y=0.0, z=0.0),
        EveSolarSystem(solar_system_id=TARGET_SYS, solar_system_name="Perimeter",
                       region_id=10000002, security=0.95, x=1.0e15, y=0.0, z=0.0),
        EveSolarSystem(solar_system_id=CJ_SYS, solar_system_name="C-J6MT-A", region_id=10000070,
                       security=-0.4, x=5.0e16, y=0.0, z=0.0),
    ])
    db.commit()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Stub every market/ESI seam the router can reach.

    Fuzzwork returns a two-sided aggregate for whatever ids are asked (buy<sell).
    gnf_local (C-J scrape) returns a flat per-type price. esi_route returns a
    2-system path (1 jump). esi_region_history returns a healthy 30-day series.
    """
    def _agg(region, ids):
        out = {}
        for tid in ids:
            # ore a touch cheaper than buying minerals outright so refine paths win
            base = {TRIT: 5.0, PYE: 10.0, VELD: 80.0, CVELD: 90.0,
                    GAS_REG: 50.0, GAS_COMP: 4000.0}.get(tid, 20.0)
            out[str(tid)] = {"buy": {"max": base * 0.9}, "sell": {"min": base}}
        return out

    monkeypatch.setattr(orr.market, "fuzzwork_aggregates_or_empty", _agg)
    monkeypatch.setattr(orr.market, "gnf_local",
                        lambda tid: {"buy": 4.5, "sell": 5.5})
    monkeypatch.setattr(orr.market, "esi_adjusted_prices",
                        lambda: {TRIT: 5.0, PYE: 10.0, VELD: 80.0, CVELD: 90.0,
                                 GAS_REG: 50.0, GAS_COMP: 4000.0})
    monkeypatch.setattr(orr.market, "esi_route",
                        lambda a, b: [a, b])
    monkeypatch.setattr(orr.market, "esi_region_history",
                        lambda region, tid: [{"average": 5.0 + i * 0.01, "volume": 1_000_000}
                                             for i in range(30)])


# ── helper builders ────────────────────────────────────────────────────────────

def _jita_src():
    return orr.SourceIn(key="jita", label="Jita", region_id=10000002, system_name="Jita")


def _cj_src():
    return orr.SourceIn(key="cj", label="C-J6MT", region_id=None,
                        system_name="C-J6MT-A", cj=True)


# ── catalog / hub endpoints ─────────────────────────────────────────────────────

def test_list_hubs():
    out = run(orr.list_hubs(current_user=USER))
    assert {h["key"] for h in out["hubs"]} == {"jita", "amarr", "dodixie", "rens", "hek"}
    assert out["cj"]["cj"] is True


def test_catalog_returns_minerals_ores(eve_db):
    out = run(orr.catalog(compressed=None, include_exotic=False, current_user=USER, eve_db=eve_db))
    mineral_ids = {m["type_id"] for m in out["minerals"]}
    assert {TRIT, PYE} <= mineral_ids
    ore_ids = {o["type_id"] for o in out["ores"]}
    assert {VELD, CVELD} <= ore_ids
    assert "moon_materials" in out


def test_catalog_compressed_filter(eve_db):
    out = run(orr.catalog(compressed=True, include_exotic=False, current_user=USER, eve_db=eve_db))
    ore_ids = {o["type_id"] for o in out["ores"]}
    assert CVELD in ore_ids and VELD not in ore_ids


def test_rigs(eve_db):
    out = run(orr.list_rigs(current_user=USER, eve_db=eve_db))
    assert out["rigs"][0]["type_id"] == RIG
    assert out["rigs"][0]["yield_bonus"] == 2.0


def test_gas_catalog(eve_db):
    out = run(orr.gas_catalog(current_user=USER, eve_db=eve_db))
    g = next(g for g in out["gases"] if g["reg_type_id"] == GAS_REG)
    assert g["comp_type_id"] == GAS_COMP
    assert g["units_per_compressed"] == pytest.approx(100.0)


def test_yields(eve_db):
    out = run(orr.yields(type_ids=f"{VELD},{CVELD}", current_user=USER, eve_db=eve_db))
    assert out[VELD]["portion_size"] == 100
    mats = {m["type_id"]: m["quantity"] for m in out[VELD]["materials"]}
    assert mats == {TRIT: 400, PYE: 200}


def test_yields_ignores_non_numeric(eve_db):
    # only the numeric token is parsed; "abc" is dropped
    out = run(orr.yields(type_ids=f"abc,{VELD}", current_user=USER, eve_db=eve_db))
    assert VELD in out


# ── parse-items / parse-minerals ────────────────────────────────────────────────

def test_parse_items_minerals(eve_db):
    body = orr.ParseNeedsRequest(text="Tritanium\t1000\nPyerite x500\nVeldspar 9", kind="mineral")
    out = run(orr.parse_items(body=body, current_user=USER, eve_db=eve_db))
    needs = {n["type_id"]: n["qty"] for n in out["needs"]}
    assert needs == {TRIT: 1000.0, PYE: 500.0}      # Veldspar is not a mineral → skipped
    assert "Veldspar" in out["skipped"]


def test_parse_items_unmatched(eve_db):
    body = orr.ParseNeedsRequest(text="Tritanium 100\nNotAThing 5", kind="mineral")
    out = run(orr.parse_items(body=body, current_user=USER, eve_db=eve_db))
    assert "NotAThing" in out["unmatched"]


def test_parse_items_any_keeps_ore(eve_db):
    body = orr.ParseNeedsRequest(text="Veldspar x9", kind="any")
    out = run(orr.parse_items(body=body, current_user=USER, eve_db=eve_db))
    assert any(n["type_id"] == VELD for n in out["needs"])


def test_parse_items_gas(eve_db):
    body = orr.ParseNeedsRequest(text="Fullerite-C50\t10", kind="gas")
    out = run(orr.parse_items(body=body, current_user=USER, eve_db=eve_db))
    assert out["needs"][0]["type_id"] == GAS_REG


def test_parse_items_empty(eve_db):
    body = orr.ParseNeedsRequest(text="   \n  ", kind="mineral")
    out = run(orr.parse_items(body=body, current_user=USER, eve_db=eve_db))
    assert out == {"needs": [], "skipped": [], "unmatched": []}


def test_parse_minerals_alias(eve_db):
    body = orr.ParseNeedsRequest(text="Tritanium 1000\nVeldspar 5", kind="mineral")
    out = run(orr.parse_minerals(body=body, current_user=USER, eve_db=eve_db))
    assert out["needs"][0]["type_id"] == TRIT
    assert "Veldspar" in out["skipped_non_mineral"]
    assert out["unmatched"] == []


# ── character-skills ─────────────────────────────────────────────────────────────

def test_character_skills(app_db):
    app_db.add(LinkedCharacter(id=1, user_id=1, character_id=CID, character_name="Refiner",
                               scopes="", is_active=True, status="active"))
    app_db.add_all([
        EsiSkill(character_id=CID, skill_id=3385, trained_level=5),   # Reprocessing
        EsiSkill(character_id=CID, skill_id=3389, trained_level=4),   # Reprocessing Efficiency
        EsiSkill(character_id=CID, skill_id=12180, trained_level=3),  # Veldspar Processing
    ])
    app_db.commit()

    out = run(orr.character_skills(character_id=1, current_user=USER, db=app_db))
    assert out["reprocessing_lvl"] == 5
    assert out["efficiency_lvl"] == 4
    assert out["ore_specific_max"] == 3
    veld = next(o for o in out["ore_specific"] if o["ore"] == "Veldspar")
    assert veld["level"] == 3


def test_character_skills_not_found(app_db):
    with pytest.raises(HTTPException) as e:
        run(orr.character_skills(character_id=999, current_user=USER, db=app_db))
    assert e.value.status_code == 404


# ── reprocess calculator ─────────────────────────────────────────────────────────

def test_reprocess_basic(eve_db):
    body = orr.ReprocessRequest(
        items=[orr.ReprocessItem(type_id=VELD, qty=1000)],
        refine=orr.RefineIn(base_yield=0.5),
    )
    out = run(orr.reprocess_calc(body=body, current_user=USER, eve_db=eve_db))
    assert out["security_band"] == "hi"
    # 1000 / 100 = 10 batches; Trit 400×10×0.5 = 2000, Pyerite 200×10×0.5 = 1000
    minerals = {m["type_id"]: m["qty"] for m in out["minerals"]}
    assert minerals == {TRIT: 2000, PYE: 1000}
    assert out["total_value"] is None
    assert out["warnings"] == []


def test_reprocess_with_rig_and_system_band(eve_db):
    body = orr.ReprocessRequest(
        items=[orr.ReprocessItem(type_id=VELD, qty=1000)],
        refine=orr.RefineIn(base_yield=0.5, rig_type_ids=[RIG]),
        system_name="C-J6MT-A",
    )
    out = run(orr.reprocess_calc(body=body, current_user=USER, eve_db=eve_db))
    assert out["security_band"] == "null"
    # null-sec rig modifier (2.1) applied → bonus 4.2%
    assert out["refine_yield"]["rig_bonus_pct"] == pytest.approx(4.2)


def test_reprocess_values_at_region(eve_db):
    body = orr.ReprocessRequest(
        items=[orr.ReprocessItem(type_id=VELD, qty=1000)],
        refine=orr.RefineIn(base_yield=0.5),
        region_id=10000002, basis="sell",
    )
    out = run(orr.reprocess_calc(body=body, current_user=USER, eve_db=eve_db))
    # 2000 Trit × 5 + 1000 Pyerite × 10 = 20000
    assert out["total_value"] == pytest.approx(20000.0)


def test_reprocess_values_at_cj(eve_db):
    body = orr.ReprocessRequest(
        items=[orr.ReprocessItem(type_id=VELD, qty=1000)],
        refine=orr.RefineIn(base_yield=0.5),
        value_cj=True, basis="split",
    )
    out = run(orr.reprocess_calc(body=body, current_user=USER, eve_db=eve_db))
    # split of gnf_local (buy 4.5, sell 5.5) → 5.0 per unit, both minerals
    assert out["total_value"] == pytest.approx((2000 + 1000) * 5.0)


def test_reprocess_unknown_type_no_warn_when_synced(eve_db):
    # an item with no reprocessing yield → empty minerals; yields ARE synced
    # (EveTypeMaterial rows exist) so no sync-hint warning is emitted.
    body = orr.ReprocessRequest(items=[orr.ReprocessItem(type_id=999999, qty=10)])
    out = run(orr.reprocess_calc(body=body, current_user=USER, eve_db=eve_db))
    assert out["minerals"] == []
    assert out["warnings"] == []


def test_reprocess_sync_hint_when_yields_missing():
    # fresh SDE with NO EveTypeMaterial rows → _yields_synced is False → sync hint
    db, engine = _mem_db(EveBase)
    try:
        db.add(EveType(type_id=VELD, type_name="Veldspar", group_id=450,
                       volume=0.1, portion_size=100, published=True))
        db.commit()
        body = orr.ReprocessRequest(items=[orr.ReprocessItem(type_id=VELD, qty=1000)])
        out = run(orr.reprocess_calc(body=body, current_user=USER, eve_db=db))
        assert out["minerals"] == []
        assert any("forced EVE sync" in w for w in out["warnings"])
    finally:
        db.close(); engine.dispose()


def test_reprocess_no_items_400(eve_db):
    with pytest.raises(HTTPException) as e:
        run(orr.reprocess_calc(body=orr.ReprocessRequest(items=[]),
                               current_user=USER, eve_db=eve_db))
    assert e.value.status_code == 400


# ── compare (mineral vs raw vs compressed) ───────────────────────────────────────

def test_compare_full_basket_recommends(eve_db):
    body = orr.CompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=TRIT, qty=10000), orr.NeedIn(type_id=PYE, qty=5000)],
        sources=[_jita_src()],
        refine=orr.RefineIn(base_yield=0.5, rig_type_ids=[RIG]),
        shipping=orr.ShippingIn(mode="regular", isk_per_jump_m3=1.0),
        basis="sell",
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert out["security_band"] == "hi"
    assert out["ore_candidates"] >= 2            # raw + compressed Veldspar
    assert {s["key"] for s in out["sources"]} == {"jita"}
    assert out["recommendation"]["strategy"] is not None
    # quantities given → basket optimisation runs (OR-Tools present)
    assert out["optimal_basket"] is not None
    assert out["optimal_basket"]["status"] in ("optimal", "feasible")
    # liquidity alerts computed from the (healthy) history → no alert flagged
    assert out["alerts"][TRIT]["alert"] is False


def test_compare_per_unit_mode(eve_db):
    # no quantities → per-unit comparison; basket optimisation skipped
    body = orr.CompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=TRIT, qty=0)],
        sources=[_jita_src()],
        refine=orr.RefineIn(base_yield=0.5),
        volatility_alert=False,
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert out["optimal_basket"] is None
    assert out["alerts"] == {}
    assert out["recommendation"]["strategy"] is not None


def test_compare_cj_source_and_flat_shipping(eve_db):
    # exercises the C-J (gnf_local / _cj_two_sided) path + flat ISK/m3 shipping
    body = orr.CompareRequest(
        target_system="C-J6MT-A",
        needs=[orr.NeedIn(type_id=TRIT, qty=1000)],
        sources=[_cj_src()],
        refine=orr.RefineIn(base_yield=0.5),
        shipping=orr.ShippingIn(mode="flat", isk_per_m3=2.0),
        volatility_alert=False,
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert {s["key"] for s in out["sources"]} == {"cj"}
    assert out["security_band"] == "null"


def test_compare_minerals_only(eve_db):
    body = orr.CompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=TRIT, qty=1000)],
        sources=[_jita_src()],
        include_raw=False, include_compressed=False, include_minerals=True,
        volatility_alert=False,
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert out["ore_candidates"] == 0
    assert out["recommendation"]["strategy"] is not None


def test_compare_jf_shipping(eve_db):
    body = orr.CompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=TRIT, qty=1000)],
        sources=[_jita_src()],
        shipping=orr.ShippingIn(mode="jf", isotopes_per_ly=100.0, isotope_price=500.0,
                                round_trip=True),
        volatility_alert=False,
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    # JF rate computed from the seeded system coordinates → a positive cost_per_m3
    assert out["sources"][0]["cost_per_m3"] > 0


def test_compare_no_needs_400(eve_db):
    body = orr.CompareRequest(needs=[], sources=[_jita_src()])
    with pytest.raises(HTTPException) as e:
        run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert e.value.status_code == 400


def test_compare_no_sources_400(eve_db):
    body = orr.CompareRequest(needs=[orr.NeedIn(type_id=TRIT, qty=1)], sources=[])
    with pytest.raises(HTTPException) as e:
        run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert e.value.status_code == 400


def test_compare_no_usable_source_400(eve_db):
    # a source with neither region_id nor cj is skipped → no usable sources
    bad = orr.SourceIn(key="x", label="No Region", region_id=None, system_name="Jita")
    body = orr.CompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=TRIT, qty=1)],
        sources=[bad],
    )
    with pytest.raises(HTTPException) as e:
        run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert e.value.status_code == 400


# ── gas-compare ──────────────────────────────────────────────────────────────────

def test_gas_compare_basic(eve_db):
    body = orr.GasCompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=GAS_REG, qty=1000)],
        sources=[_jita_src()],
        shipping=orr.ShippingIn(mode="flat", isk_per_m3=1.0),
    )
    out = run(orr.compare_gas(body=body, current_user=USER, eve_db=eve_db))
    assert out["recommendation"]["strategy"] is not None
    gas = out["gases"][0]
    assert gas["reg_type_id"] == GAS_REG
    assert gas["units_per_compressed"] == pytest.approx(100.0)
    assert out["alerts"][GAS_REG]["alert"] is False


def test_gas_compare_no_needs_400(eve_db):
    body = orr.GasCompareRequest(needs=[], sources=[_jita_src()])
    with pytest.raises(HTTPException) as e:
        run(orr.compare_gas(body=body, current_user=USER, eve_db=eve_db))
    assert e.value.status_code == 400


def test_gas_compare_no_sources_400(eve_db):
    body = orr.GasCompareRequest(needs=[orr.NeedIn(type_id=GAS_REG, qty=1)], sources=[])
    with pytest.raises(HTTPException) as e:
        run(orr.compare_gas(body=body, current_user=USER, eve_db=eve_db))
    assert e.value.status_code == 400


def test_gas_compare_unrecognised_gas_404(eve_db):
    body = orr.GasCompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=TRIT, qty=10)],   # Tritanium is not a gas
        sources=[_jita_src()],
    )
    with pytest.raises(HTTPException) as e:
        run(orr.compare_gas(body=body, current_user=USER, eve_db=eve_db))
    assert e.value.status_code == 404


def test_gas_compare_no_usable_source_400(eve_db):
    bad = orr.SourceIn(key="x", label="No Region", region_id=None, system_name="Jita")
    body = orr.GasCompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=GAS_REG, qty=1)],
        sources=[bad],
    )
    with pytest.raises(HTTPException) as e:
        run(orr.compare_gas(body=body, current_user=USER, eve_db=eve_db))
    assert e.value.status_code == 400


# ── extra branch coverage ───────────────────────────────────────────────────────

def test_compare_unknown_target_system_uses_hi_band(eve_db):
    # target system not in SDE → _resolve_system None → band defaults to "hi";
    # regular shipping with an unresolvable src system → "system not found" warning.
    body = orr.CompareRequest(
        target_system="Nowhere",
        needs=[orr.NeedIn(type_id=TRIT, qty=100)],
        sources=[orr.SourceIn(key="jita", label="Jita", region_id=10000002,
                              system_name="Jita")],
        shipping=orr.ShippingIn(mode="regular", isk_per_jump_m3=1.0),
        volatility_alert=False,
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert out["security_band"] == "hi"
    assert any("system not found" in w for w in out["warnings"])
    assert out["sources"][0]["cost_per_m3"] == 0.0


def test_compare_no_ores_yield_selected_mineral_warns(eve_db):
    # request raw/compressed ore for a mineral no seeded ore yields → "no ores
    # found yielding the selected minerals" warning (yields ARE synced).
    body = orr.CompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=11399, qty=0)],   # Morphite — no ore yields it here
        sources=[_jita_src()],
        include_raw=True, include_compressed=True,
        volatility_alert=False,
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert out["ore_candidates"] == 0
    assert any("no ores found yielding" in w for w in out["warnings"])


def test_compare_adjusted_prices_failure_is_swallowed(eve_db, monkeypatch):
    # esi_adjusted_prices raising must be caught → adjusted = {} → still resolves.
    def _boom():
        raise RuntimeError("ESI down")
    monkeypatch.setattr(orr.market, "esi_adjusted_prices", _boom)
    body = orr.CompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=TRIT, qty=100)],
        sources=[_jita_src()],
        volatility_alert=False,
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert out["recommendation"]["strategy"] is not None


def test_compare_volatility_thin_market_alert(eve_db, monkeypatch):
    # short history (<5 rows) → flagged as thin market with an alert.
    monkeypatch.setattr(orr.market, "esi_region_history",
                        lambda region, tid: [{"average": 5.0, "volume": 100}])
    body = orr.CompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=TRIT, qty=100)],
        sources=[_jita_src()],
        volatility_alert=True,
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert out["alerts"][TRIT]["alert"] is True
    assert "no recent market history" in out["alerts"][TRIT]["reason"]


def test_compare_volatility_zero_volume_alert(eve_db, monkeypatch):
    # enough history but no traded volume → illiquid alert.
    monkeypatch.setattr(orr.market, "esi_region_history",
                        lambda region, tid: [{"average": 5.0 + i * 0.01, "volume": 0}
                                             for i in range(30)])
    body = orr.CompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=TRIT, qty=100)],
        sources=[_jita_src()],
        volatility_alert=True,
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert out["alerts"][TRIT]["alert"] is True
    assert out["alerts"][TRIT]["avg_volume"] == 0.0


def test_compare_regular_shipping_route_unavailable(eve_db, monkeypatch):
    # ESI route None → "ESI route unavailable" warning, transport 0.
    monkeypatch.setattr(orr.market, "esi_route", lambda a, b: None)
    body = orr.CompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=TRIT, qty=100)],
        sources=[_jita_src()],
        shipping=orr.ShippingIn(mode="regular", isk_per_jump_m3=1.0),
        volatility_alert=False,
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert any("ESI route unavailable" in w for w in out["warnings"])
    assert out["sources"][0]["cost_per_m3"] == 0.0


def test_gas_compare_no_compression_ratio_warns(eve_db):
    # fresh SDE: a gas with NO compressed variant → units_per_compressed None →
    # "no compression ratio" warning (yields synced).
    db, engine = _mem_db(EveBase)
    try:
        db.add_all([
            EveGroup(group_id=711, category_id=25, group_name="Gas", published=True),
            EveType(type_id=GAS_REG, type_name="Fullerite-C50", group_id=711,
                    volume=1.0, portion_size=1, published=True),
            # an unrelated EveTypeMaterial so _yields_synced is True
            EveType(type_id=VELD, type_name="Veldspar", group_id=711,
                    volume=0.1, portion_size=100, published=True),
            EveTypeMaterial(type_id=VELD, material_type_id=TRIT, quantity=400),
            EveSolarSystem(solar_system_id=TARGET_SYS, solar_system_name="Perimeter",
                           region_id=10000002, security=0.95, x=0.0, y=0.0, z=0.0),
        ])
        db.commit()
        body = orr.GasCompareRequest(
            target_system="Perimeter",
            needs=[orr.NeedIn(type_id=GAS_REG, qty=100)],
            sources=[orr.SourceIn(key="jita", label="Jita", region_id=10000002)],
            volatility_alert=False,
        )
        out = run(orr.compare_gas(body=body, current_user=USER, eve_db=db))
        assert any("compression ratio" in w for w in out["warnings"])
    finally:
        db.close(); engine.dispose()


def test_resolve_system_prefix_fallback(eve_db):
    # exact name miss, prefix hit: "C-J6MT" resolves to "C-J6MT-A".
    sys = orr._resolve_system(eve_db, "C-J6MT")
    assert sys is not None and sys.solar_system_name == "C-J6MT-A"
    assert orr._resolve_system(eve_db, None) is None


def test_gas_compare_with_quantities_recommends_form(eve_db):
    # quantities given → strategy totals computed; both regular and compressed
    # PathOptions resolve (compressed price present in the stub).
    body = orr.GasCompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=GAS_REG, qty=1000)],
        sources=[_jita_src()],
        shipping=orr.ShippingIn(mode="flat", isk_per_m3=1.0),
        decompression_loss_pct=5.0,
        volatility_alert=False,
    )
    out = run(orr.compare_gas(body=body, current_user=USER, eve_db=eve_db))
    gas = out["gases"][0]
    assert gas["reg_best"] is not None and gas["comp_best"] is not None
    assert gas["recommended"]["effective_cost"] is not None
    assert out["recommendation"]["total_cost"] is not None


def test_gas_compare_adjusted_failure_swallowed(eve_db, monkeypatch):
    def _boom():
        raise RuntimeError("ESI down")
    monkeypatch.setattr(orr.market, "esi_adjusted_prices", _boom)
    body = orr.GasCompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=GAS_REG, qty=10)],
        sources=[_jita_src()],
        volatility_alert=False,
    )
    out = run(orr.compare_gas(body=body, current_user=USER, eve_db=eve_db))
    assert out["recommendation"]["strategy"] is not None


def test_compare_basket_skips_unpriced_options(eve_db, monkeypatch):
    # Fuzzwork returns prices only for the mineral, not the ores → in the basket
    # builder, ore options are skipped (px None / no usable yields) but the
    # direct-mineral option still solves the basket.
    def _agg(region, ids):
        return {str(TRIT): {"buy": {"max": 4.0}, "sell": {"min": 5.0}}}
    monkeypatch.setattr(orr.market, "fuzzwork_aggregates_or_empty", _agg)
    body = orr.CompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=TRIT, qty=1000)],
        sources=[_jita_src()],
        include_raw=True, include_compressed=True, include_minerals=True,
        volatility_alert=False,
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert out["optimal_basket"]["status"] in ("optimal", "feasible")
    assert all(b["kind"] == "mineral" for b in out["optimal_basket"]["buys"])


def test_compare_jf_same_system_zero_rate(eve_db):
    # JF shipping where the source system IS the target → distance 0 → rate 0.
    body = orr.CompareRequest(
        target_system="Jita",
        needs=[orr.NeedIn(type_id=TRIT, qty=100)],
        sources=[_jita_src()],   # system_name "Jita" == target
        shipping=orr.ShippingIn(mode="jf", isotopes_per_ly=100.0, isotope_price=500.0),
        volatility_alert=False,
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert out["sources"][0]["cost_per_m3"] == 0.0


def test_compare_volatility_no_region_source(eve_db):
    # volatility_alert on, but the only source has no region (C-J) → region None →
    # _volatility_alerts early-returns {} (no history fetched).
    body = orr.CompareRequest(
        target_system="C-J6MT-A",
        needs=[orr.NeedIn(type_id=TRIT, qty=100)],
        sources=[_cj_src()],
        shipping=orr.ShippingIn(mode="flat", isk_per_m3=1.0),
        volatility_alert=True,
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert out["alerts"] == {}


def test_compare_basket_optimisation_failure_is_non_fatal(eve_db, monkeypatch):
    # optimize_basket raising (e.g. solver issue) → caught, warning added,
    # optimal_basket stays None, the rest of the payload still returns.
    def _boom(needs, options):
        raise RuntimeError("solver exploded")
    monkeypatch.setattr(orr.ore_basket, "optimize_basket", _boom)
    body = orr.CompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=TRIT, qty=1000)],
        sources=[_jita_src()],
        volatility_alert=False,
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert out["optimal_basket"] is None
    assert any("basket optimisation skipped" in w for w in out["warnings"])


def test_compare_basket_ore_yields_only_unneeded_mineral(eve_db, monkeypatch):
    # need only Pyerite. Add a Trit-only ore (Plagioclase); request only Pyerite.
    # It is priced (px not None) but its yield restricted to needed minerals is
    # empty → skipped in the basket builder (line: not y → continue).
    def _agg(region, ids):
        return {str(tid): {"buy": {"max": 4.0}, "sell": {"min": 5.0}} for tid in ids}
    monkeypatch.setattr(orr.market, "fuzzwork_aggregates_or_empty", _agg)
    eve_db.add_all([
        EveType(type_id=1234, type_name="Plagioclase", group_id=450, volume=0.35,
                portion_size=100, published=True),
        EveTypeMaterial(type_id=1234, material_type_id=TRIT, quantity=100),
    ])
    eve_db.commit()
    body = orr.CompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=PYE, qty=1000)],
        sources=[_jita_src()],
        include_raw=True, include_compressed=False, include_minerals=True,
        volatility_alert=False,
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert out["optimal_basket"]["status"] in ("optimal", "feasible")


def test_basis_price_split_one_sided():
    assert orr._basis_price({"buy": 4.0, "sell": 6.0}, "split") == pytest.approx(5.0)
    assert orr._basis_price({"buy": 4.0, "sell": None}, "split") == 4.0
    assert orr._basis_price({"buy": None, "sell": 6.0}, "split") == 6.0
    assert orr._basis_price({"buy": 4.0, "sell": 6.0}, "buy") == 4.0


def test_fnum_handles_bad_values():
    assert orr._fnum("3.5") == pytest.approx(3.5)
    assert orr._fnum(None) is None
    assert orr._fnum("not-a-number") is None


def test_parse_items_qty_first_tab_format(eve_db):
    # "Qty<tab>Name" (multibuy reversed) → qty is the leading token.
    body = orr.ParseNeedsRequest(text="1000\tTritanium", kind="mineral")
    out = run(orr.parse_items(body=body, current_user=USER, eve_db=eve_db))
    assert out["needs"][0] == {"type_id": TRIT, "name": "Tritanium", "qty": 1000.0}


def test_parse_items_tab_no_numbers_qty_zero(eve_db):
    # "Name<tab>Name" with no numeric side → qty defaults to 0.
    body = orr.ParseNeedsRequest(text="Tritanium\tPyerite", kind="any")
    out = run(orr.parse_items(body=body, current_user=USER, eve_db=eve_db))
    # first token "Tritanium" kept at qty 0 (second token is the discarded "name")
    assert any(n["type_id"] == TRIT and n["qty"] == 0.0 for n in out["needs"])


def test_parse_items_bare_name_qty_zero(eve_db):
    # a plain name with no quantity → qty 0 (regex no-match branch).
    body = orr.ParseNeedsRequest(text="Tritanium", kind="mineral")
    out = run(orr.parse_items(body=body, current_user=USER, eve_db=eve_db))
    assert out["needs"][0] == {"type_id": TRIT, "name": "Tritanium", "qty": 0.0}


def test_parse_items_moon_kind(eve_db):
    # 'moon' kind keeps only group-427 materials; Tritanium (group 18) is skipped.
    body = orr.ParseNeedsRequest(text="Tritanium 5", kind="moon")
    out = run(orr.parse_items(body=body, current_user=USER, eve_db=eve_db))
    assert out["needs"] == []
    assert "Tritanium" in out["skipped"]


def test_compare_basket_ore_unpriced_no_adjusted(eve_db, monkeypatch):
    # ore has no market price and no ESI adjusted fallback → skipped in the basket
    # builder (line: px is None → continue); the mineral still solves it.
    def _agg(region, ids):
        return {str(TRIT): {"buy": {"max": 4.0}, "sell": {"min": 5.0}}}
    monkeypatch.setattr(orr.market, "fuzzwork_aggregates_or_empty", _agg)
    monkeypatch.setattr(orr.market, "esi_adjusted_prices", lambda: {})
    body = orr.CompareRequest(
        target_system="Perimeter",
        needs=[orr.NeedIn(type_id=TRIT, qty=1000)],
        sources=[_jita_src()],
        include_raw=True, include_compressed=True, include_minerals=True,
        volatility_alert=False,
    )
    out = run(orr.compare_acquisition(body=body, current_user=USER, eve_db=eve_db))
    assert out["optimal_basket"]["status"] in ("optimal", "feasible")
    assert all(b["kind"] == "mineral" for b in out["optimal_basket"]["buys"])
