"""Reprocessing presets + refine-warehouse-ore endpoint.

Driven the project's no-HTTP way: the async endpoint functions are called directly with
seeded in-memory SQLite sessions; the only network touch (Jita aggregates for cost
allocation) is monkeypatched.
"""
import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import inventory_router as ir
from app.core.database import Base, InventoryItem, ReprocessingPreset
from app.core.database_eve import EveBase, EveType, EveGroup, EveTypeMaterial

USER = SimpleNamespace(id=1)


def run(coro):
    return asyncio.run(coro)


def _mem_db(base):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


@pytest.fixture
def app_db():
    s, e = _mem_db(Base); yield s; s.close(); e.dispose()


@pytest.fixture
def eve_db():
    s, e = _mem_db(EveBase); yield s; s.close(); e.dispose()


def _seed_sde(eve_db):
    eve_db.add_all([
        EveType(type_id=1230, type_name="Veldspar", group_id=462, volume=0.1, portion_size=100, published=True),
        EveType(type_id=34, type_name="Tritanium", group_id=18, volume=0.01, published=True),
        EveGroup(group_id=462, category_id=25, group_name="Veldspar"),
        EveTypeMaterial(type_id=1230, material_type_id=34, quantity=415),
    ])
    eve_db.commit()


def _seed_ore(app_db, qty=1000, price=5.0):
    item = InventoryItem(user_id=1, eve_type_id=1230, name="Veldspar", quantity=qty,
                         price=price, flow="input", item_status="in_stock")
    app_db.add(item); app_db.commit(); app_db.refresh(item)
    return item


def _mock_jita(monkeypatch):
    monkeypatch.setattr(ir.market, "fuzzwork_aggregates_or_empty",
                        lambda region, ids: {"34": {"sell": {"percentile": 5.0}, "buy": {"percentile": 4.0}}})


# ── preset CRUD ────────────────────────────────────────────────────────────────

def test_preset_crud(app_db):
    p = run(ir.create_preset(body=ir.PresetIn(name="Athanor T2", base_yield=0.54, tax_pct=2.0,
                                              reprocessing_lvl=5, efficiency_lvl=5),
                             current_user=USER, db=app_db))
    assert p["name"] == "Athanor T2" and p["base_yield"] == 0.54 and p["reprocessing_lvl"] == 5
    listed = run(ir.list_presets(current_user=USER, db=app_db))
    assert len(listed) == 1
    upd = run(ir.update_preset(preset_id=p["id"], body=ir.PresetIn(name="Athanor", base_yield=0.5),
                               current_user=USER, db=app_db))
    assert upd["name"] == "Athanor" and upd["base_yield"] == 0.5
    run(ir.delete_preset(preset_id=p["id"], current_user=USER, db=app_db))
    assert run(ir.list_presets(current_user=USER, db=app_db)) == []


# ── reprocess ──────────────────────────────────────────────────────────────────

def test_reprocess_creates_minerals_with_cost_basis(app_db, eve_db, monkeypatch):
    _seed_sde(eve_db)
    ore = _seed_ore(app_db, qty=1000, price=5.0)
    _mock_jita(monkeypatch)
    p = run(ir.create_preset(body=ir.PresetIn(name="NPC", base_yield=0.5), current_user=USER, db=app_db))

    out = run(ir.reprocess_inventory(body=ir.ReprocessIn(preset_id=p["id"], item_ids=[ore.id], basis="sell"),
                                     current_user=USER, db=app_db, eve_db=eve_db))
    # 1000 Veldspar → 10 batches × 415 = 4150 perfect × 0.50 yield = 2075 Tritanium
    assert out["effective_yield"] == 0.5
    assert out["ore_cost"] == 5000.0                     # 5 ISK × 1000 refined units
    mn = out["minerals"][0]
    assert mn["type_id"] == 34 and mn["quantity"] == 2075 and mn["value"] == 10375.0
    assert mn["unit_cost"] == round(5000.0 / 2075, 4)    # ore cost carried onto the mineral

    # ore consumed, mineral lot created and flagged source="reprocess"
    app_db.refresh(ore)
    assert ore.item_status == "used"
    minerals = app_db.query(InventoryItem).filter(InventoryItem.source == "reprocess").all()
    assert len(minerals) == 1
    assert minerals[0].eve_type_id == 34 and minerals[0].quantity == 2075


def test_reprocess_leaves_sub_batch_leftover(app_db, eve_db, monkeypatch):
    _seed_sde(eve_db)
    ore = _seed_ore(app_db, qty=150, price=5.0)   # only 1 full batch (100); 50 left over
    _mock_jita(monkeypatch)
    p = run(ir.create_preset(body=ir.PresetIn(name="NPC", base_yield=0.5), current_user=USER, db=app_db))

    out = run(ir.reprocess_inventory(body=ir.ReprocessIn(preset_id=p["id"], item_ids=[ore.id]),
                                     current_user=USER, db=app_db, eve_db=eve_db))
    assert out["ore_cost"] == 500.0          # only the 100 refined units cost
    app_db.refresh(ore)
    assert ore.item_status == "in_stock" and ore.quantity == 50   # leftover stays


def test_reprocessing_stock_lists_only_ore(app_db, eve_db):
    _seed_sde(eve_db)
    _seed_ore(app_db)
    # a non-ore item must not appear
    app_db.add(InventoryItem(user_id=1, eve_type_id=34, name="Tritanium", quantity=5,
                             flow="input", item_status="in_stock"))
    app_db.commit()
    stock = run(ir.reprocessing_stock(current_user=USER, db=app_db, eve_db=eve_db))
    assert [s["type_id"] for s in stock] == [1230]
