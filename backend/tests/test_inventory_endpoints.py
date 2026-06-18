"""
Inventory endpoints (personal warehouse): preview/bulk parse, batch + single add,
list/clear, sell/use, split, and CRUD with 404/400 branches. Driven against
in-memory SQLite the project's no-HTTP way — the async route functions are called
directly with seeded sessions for the Depends params. The SDE-resolution helper
(_resolve_eve_type) opens its own session via EveSessionLocal, so we monkeypatch
that factory to hand back an in-memory EveBase session; no network is touched.
"""
import asyncio
import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import inventory_router as inv
from app.api.inventory_router import (
    InventoryCreate, InventoryUpdate, BulkParseRequest, BatchCreate,
    BatchItemCreate, SellRequest, UseRequest, SplitRequest,
)
from app.core.database import Base, UserDB, InventoryItem, Projects, StockMovement
from app.core.database_eve import EveBase, EveType
from app.core.schemas import ProjectsType, ProjectsStatus

USER = SimpleNamespace(id=1)


def run(coro):
    return asyncio.run(coro)


def _mem_db(base):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


@pytest.fixture
def app_db():
    session, engine = _mem_db(Base)
    session.add(UserDB(id=1, username="u", email="u@example.com", hashed_password="x"))
    session.commit()
    yield session
    session.close(); engine.dispose()


@pytest.fixture
def eve_db():
    session, engine = _mem_db(EveBase)
    # Tritanium: known to SDE with a per-unit volume.
    session.add(EveType(type_id=34, type_name="Tritanium", group_id=18, volume=0.01, published=True))
    session.commit()
    yield session
    session.close(); engine.dispose()


@pytest.fixture(autouse=True)
def _patch_eve_session(monkeypatch, eve_db):
    """Routes that resolve names open EveSessionLocal() themselves; hand them our
    in-memory SDE session and make .close() a no-op so the fixture owns teardown."""
    monkeypatch.setattr(eve_db, "close", lambda: None)
    monkeypatch.setattr(inv, "EveSessionLocal", lambda: eve_db)


def _seed_project(app_db, pid=10, name="Proj"):
    app_db.add(Projects(
        id=pid, name=name, created_by=1, organisation_id=1,
        project_type=ProjectsType.INTERNAL, status=ProjectsStatus.ACTIVE,
    ))
    app_db.commit()


def _seed_item(app_db, **kw):
    defaults = dict(user_id=1, name="Tritanium", quantity=1000, volume=0.01,
                    price=5.0, place="Jita", flow="input", item_status="in_stock")
    defaults.update(kw)
    item = InventoryItem(**defaults)
    app_db.add(item)
    app_db.commit()
    app_db.refresh(item)
    return item


# ── preview (no save) ─────────────────────────────────────────────────────────

def test_preview_resolves_and_warns(app_db):
    body = BulkParseRequest(text="Tritanium\t100\nUnobtanium\t5\nbadline")
    res = run(inv.preview_bulk(body=body, current_user=USER))
    by_name = {i.name: i for i in res.items}
    assert by_name["Tritanium"].eve_type_id == 34
    assert by_name["Tritanium"].volume == pytest.approx(0.01)
    assert by_name["Tritanium"].volume_total == pytest.approx(1.0)  # 0.01 * 100
    assert by_name["Tritanium"].warning is None
    # unknown name still previewed, but flagged
    assert by_name["Unobtanium"].eve_type_id is None
    assert "not found in SDE" in by_name["Unobtanium"].warning
    # the malformed line (no tab) produced a parse warning, not an item
    assert any("badline" in w for w in res.warnings)


# ── batch add ───────────────────────────────────────────────────────────────

def test_batch_add_creates_rows(app_db):
    body = BatchCreate(items=[
        BatchItemCreate(name="Tritanium", quantity=100, eve_type_id=34, volume=0.01),
        BatchItemCreate(name="Pyerite", quantity=50, flow="output"),
    ])
    out = run(inv.batch_add(body=body, current_user=USER, db=app_db))
    assert len(out) == 2
    assert {o.name for o in out} == {"Tritanium", "Pyerite"}
    assert app_db.query(InventoryItem).count() == 2
    pyerite = next(o for o in out if o.name == "Pyerite")
    assert pyerite.flow == "output"


def test_batch_add_project_not_found(app_db):
    body = BatchCreate(items=[BatchItemCreate(name="X", quantity=1, project_id=999)])
    with pytest.raises(inv.HTTPException) as ei:
        run(inv.batch_add(body=body, current_user=USER, db=app_db))
    assert ei.value.status_code == 404


def test_batch_add_with_valid_project(app_db):
    _seed_project(app_db, pid=10)
    body = BatchCreate(items=[BatchItemCreate(name="X", quantity=1, project_id=10)])
    out = run(inv.batch_add(body=body, current_user=USER, db=app_db))
    assert out[0].project_id == 10


# ── single add (with SDE auto-resolve) ───────────────────────────────────────

def test_add_item_autoresolves_type_and_volume(app_db):
    body = InventoryCreate(name="Tritanium", quantity=100)  # no eve_type_id/volume
    out = run(inv.add_item(body=body, current_user=USER, db=app_db))
    assert out.eve_type_id == 34
    assert out.volume == pytest.approx(0.01)  # pulled from SDE
    assert out.quantity == 100


def test_add_item_unknown_name_no_type(app_db):
    body = InventoryCreate(name="Mystery Goo", quantity=3)
    out = run(inv.add_item(body=body, current_user=USER, db=app_db))
    assert out.eve_type_id is None
    assert out.volume is None


def test_add_item_project_not_found(app_db):
    body = InventoryCreate(name="X", quantity=1, project_id=999)
    with pytest.raises(inv.HTTPException) as ei:
        run(inv.add_item(body=body, current_user=USER, db=app_db))
    assert ei.value.status_code == 404


# ── bulk add (parse + persist) ───────────────────────────────────────────────

def test_bulk_add_parses_and_persists(app_db):
    # mix: Name\tQty (resolved), Qty\tName (EVE multi-buy), unknown name, blank line
    body = BulkParseRequest(text="Tritanium\t1000\n5\tUnknownThing\n\n", place="Amarr")
    res = run(inv.bulk_add_items(body=body, current_user=USER, db=app_db))
    assert res.created == 2
    assert app_db.query(InventoryItem).count() == 2
    names = {i.name for i in res.items}
    assert names == {"Tritanium", "UnknownThing"}
    trit = next(i for i in res.items if i.name == "Tritanium")
    assert trit.eve_type_id == 34 and trit.volume == pytest.approx(0.01)
    assert trit.place == "Amarr"
    # the unknown name was stored without a type link and warned about
    assert any("UnknownThing" in w for w in res.warnings)


def test_bulk_add_project_not_found(app_db):
    body = BulkParseRequest(text="Tritanium\t1", project_id=999)
    with pytest.raises(inv.HTTPException) as ei:
        run(inv.bulk_add_items(body=body, current_user=USER, db=app_db))
    assert ei.value.status_code == 404


def test_bulk_add_skips_malformed_lines(app_db):
    body = BulkParseRequest(text="no-tab-here\nTritanium\t2")
    res = run(inv.bulk_add_items(body=body, current_user=USER, db=app_db))
    assert res.created == 1
    assert res.skipped == 1


def test_bulk_add_both_columns_numeric_is_qty_name(app_db):
    # "8\t34" — both numeric → treated as Qty<tab>Name (EVE multi-buy style):
    # qty=8, name="34" (stored as-is, no SDE link).
    body = BulkParseRequest(text="8\t34")
    res = run(inv.bulk_add_items(body=body, current_user=USER, db=app_db))
    assert res.created == 1
    assert res.items[0].name == "34" and res.items[0].quantity == 8


def test_preview_rejects_non_positive_quantity(app_db):
    # "Tritanium\t0" parses but qty<=0 is rejected with a warning, no item emitted
    res = run(inv.preview_bulk(body=BulkParseRequest(text="Tritanium\t0"), current_user=USER))
    assert res.items == []
    assert any("must be positive" in w for w in res.warnings)


# ── list + clear ──────────────────────────────────────────────────────────────

def test_list_inventory_default_in_stock(app_db):
    _seed_item(app_db, name="A", item_status="in_stock")
    _seed_item(app_db, name="B", item_status="sold")
    _seed_item(app_db, name="C", item_status=None)  # legacy NULL treated as in_stock
    rows = run(inv.list_inventory(current_user=USER, db=app_db))
    names = {r.name for r in rows}
    assert names == {"A", "C"}  # sold hidden by default


def test_list_inventory_status_all_and_filters(app_db):
    _seed_project(app_db, pid=10)
    _seed_item(app_db, name="A", item_status="sold", place="Jita", project_id=10)
    _seed_item(app_db, name="B", item_status="in_stock", place="Amarr")
    # status=all returns everything
    assert {r.name for r in run(inv.list_inventory(item_status="all", current_user=USER, db=app_db))} == {"A", "B"}
    # place filter (ilike)
    jita = run(inv.list_inventory(item_status="all", place="jit", current_user=USER, db=app_db))
    assert {r.name for r in jita} == {"A"}
    # project filter
    proj = run(inv.list_inventory(item_status="all", project_id=10, current_user=USER, db=app_db))
    assert {r.name for r in proj} == {"A"}


def test_list_inventory_by_status_used(app_db):
    _seed_item(app_db, name="U", item_status="used")
    rows = run(inv.list_inventory(item_status="used", current_user=USER, db=app_db))
    assert {r.name for r in rows} == {"U"}


def test_list_inventory_by_organisation(app_db):
    # project 10 belongs to org 1; its items are reachable via organisation_id filter
    _seed_project(app_db, pid=10)
    _seed_item(app_db, name="A", project_id=10, item_status="in_stock")
    _seed_item(app_db, name="B")  # no project → excluded by org filter
    rows = run(inv.list_inventory(item_status="all", organisation_id=1, current_user=USER, db=app_db))
    assert {r.name for r in rows} == {"A"}
    # an org with no projects yields nothing (falls back to [-1])
    empty = run(inv.list_inventory(item_status="all", organisation_id=999, current_user=USER, db=app_db))
    assert empty == []


def test_clear_inventory_all_and_by_project(app_db):
    _seed_project(app_db, pid=10)
    _seed_item(app_db, name="A", project_id=10)
    _seed_item(app_db, name="B")  # no project
    run(inv.clear_inventory(project_id=10, current_user=USER, db=app_db))
    assert {i.name for i in app_db.query(InventoryItem).all()} == {"B"}
    run(inv.clear_inventory(current_user=USER, db=app_db))
    assert app_db.query(InventoryItem).count() == 0


# ── sell ──────────────────────────────────────────────────────────────────────

def test_sell_full_lot(app_db):
    item = _seed_item(app_db, quantity=100, price=5.0)
    out = run(inv.sell_item(item_id=item.id, body=SellRequest(sale_price=8.0),
                            current_user=USER, db=app_db))
    assert out.id == item.id  # full lot → same row marked sold
    assert out.item_status == "sold"
    assert out.sale_price == pytest.approx(8.0)
    mv = app_db.query(StockMovement).one()
    assert mv.direction == "out" and mv.reason == "Sold"
    assert mv.total_cost == pytest.approx(800.0)  # 8 * 100


def test_sell_partial_splits_off(app_db):
    item = _seed_item(app_db, quantity=100)
    out = run(inv.sell_item(item_id=item.id, body=SellRequest(sale_price=8.0, quantity=30),
                            current_user=USER, db=app_db))
    assert out.id != item.id  # new lot for the 30 sold
    assert out.quantity == 30 and out.item_status == "sold"
    app_db.refresh(item)
    assert item.quantity == 70 and item.item_status == "in_stock"


def test_sell_item_not_found(app_db):
    with pytest.raises(inv.HTTPException) as ei:
        run(inv.sell_item(item_id=999, body=SellRequest(sale_price=1.0),
                          current_user=USER, db=app_db))
    assert ei.value.status_code == 404


# ── use ─────────────────────────────────────────────────────────────────────

def test_use_full_lot(app_db):
    item = _seed_item(app_db, quantity=50, price=2.0)
    out = run(inv.use_item(item_id=item.id, body=UseRequest(reason="refuel"),
                           current_user=USER, db=app_db))
    assert out.item_status == "used"
    mv = app_db.query(StockMovement).one()
    assert mv.reason == "Used: refuel"
    assert mv.total_cost == pytest.approx(100.0)  # 2 * 50


def test_use_partial_no_reason(app_db):
    item = _seed_item(app_db, quantity=50, price=None)
    out = run(inv.use_item(item_id=item.id, body=UseRequest(quantity=20),
                           current_user=USER, db=app_db))
    assert out.quantity == 20 and out.item_status == "used"
    mv = app_db.query(StockMovement).one()
    assert mv.reason == "Used (internal)"
    assert mv.total_cost == pytest.approx(0.0)  # price None → 0


def test_use_item_not_found(app_db):
    with pytest.raises(inv.HTTPException) as ei:
        run(inv.use_item(item_id=999, body=UseRequest(), current_user=USER, db=app_db))
    assert ei.value.status_code == 404


# ── split (success + both 400s + 404) ────────────────────────────────────────

def test_split_success(app_db):
    item = _seed_item(app_db, quantity=100, item_status="in_stock")
    original, clone = run(inv.split_item(item_id=item.id, body=SplitRequest(quantity=30),
                                         current_user=USER, db=app_db))
    assert original.id == item.id and original.quantity == 70
    assert clone.id != item.id and clone.quantity == 30
    assert clone.item_status == "in_stock"


def test_split_too_large_400(app_db):
    item = _seed_item(app_db, quantity=100)
    with pytest.raises(inv.HTTPException) as ei:
        run(inv.split_item(item_id=item.id, body=SplitRequest(quantity=100),
                           current_user=USER, db=app_db))
    assert ei.value.status_code == 400
    assert "less than" in ei.value.detail


def test_split_reserved_by_delivery_400(app_db):
    item = _seed_item(app_db, quantity=100, delivery_id=7)
    with pytest.raises(inv.HTTPException) as ei:
        run(inv.split_item(item_id=item.id, body=SplitRequest(quantity=10),
                           current_user=USER, db=app_db))
    assert ei.value.status_code == 400
    assert "reserved by a delivery" in ei.value.detail


def test_split_item_not_found(app_db):
    with pytest.raises(inv.HTTPException) as ei:
        run(inv.split_item(item_id=999, body=SplitRequest(quantity=1),
                           current_user=USER, db=app_db))
    assert ei.value.status_code == 404


# ── get / update / delete (+ 404s) ───────────────────────────────────────────

def test_get_item(app_db):
    item = _seed_item(app_db, name="Tritanium")
    out = run(inv.get_item(item_id=item.id, current_user=USER, db=app_db))
    assert out.id == item.id and out.name == "Tritanium"


def test_get_item_not_found(app_db):
    with pytest.raises(inv.HTTPException) as ei:
        run(inv.get_item(item_id=999, current_user=USER, db=app_db))
    assert ei.value.status_code == 404


def test_update_item_fields(app_db):
    _seed_project(app_db, pid=10)
    item = _seed_item(app_db, quantity=100, price=5.0, place="Jita", note=None)
    out = run(inv.update_item(item_id=item.id, current_user=USER, db=app_db,
                              body=InventoryUpdate(quantity=200, price=6.0, place="Amarr",
                                                   note="moved", project_id=10)))
    assert out.quantity == 200 and out.price == pytest.approx(6.0)
    assert out.place == "Amarr" and out.note == "moved"
    assert out.project_id == 10
    assert out.updated_at is not None


def test_update_item_bad_project_404(app_db):
    item = _seed_item(app_db)
    with pytest.raises(inv.HTTPException) as ei:
        run(inv.update_item(item_id=item.id, current_user=USER, db=app_db,
                            body=InventoryUpdate(project_id=999)))
    assert ei.value.status_code == 404


def test_update_item_not_found(app_db):
    with pytest.raises(inv.HTTPException) as ei:
        run(inv.update_item(item_id=999, current_user=USER, db=app_db,
                            body=InventoryUpdate(quantity=5)))
    assert ei.value.status_code == 404


def test_delete_item(app_db):
    item = _seed_item(app_db)
    run(inv.delete_item(item_id=item.id, current_user=USER, db=app_db))
    assert app_db.query(InventoryItem).count() == 0


def test_delete_item_not_found(app_db):
    with pytest.raises(inv.HTTPException) as ei:
        run(inv.delete_item(item_id=999, current_user=USER, db=app_db))
    assert ei.value.status_code == 404
