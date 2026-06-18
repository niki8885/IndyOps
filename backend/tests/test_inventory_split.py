"""Stack splitting — _split_off carves a new lot off an inventory item."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.inventory_router import _split_off
from app.core.database import Base, InventoryItem


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[InventoryItem.__table__])
    return sessionmaker(bind=engine)()


def test_split_carves_new_lot():
    s = _session()
    item = InventoryItem(user_id=1, name="Tritanium", quantity=1_000_000,
                         volume=0.01, price=5.0, place="Jita", flow="input")
    s.add(item)
    s.commit()

    clone = _split_off(s, item, 500_000)
    s.commit()

    assert item.quantity == 500_000
    assert clone.quantity == 500_000
    assert clone.id != item.id
    # metadata carries over so the two halves are interchangeable
    assert clone.place == "Jita"
    assert clone.price == pytest.approx(5.0)
    assert clone.name == "Tritanium"
    s.close()


def test_split_uneven():
    s = _session()
    item = InventoryItem(user_id=1, name="Pyerite", quantity=100, flow="input")
    s.add(item)
    s.commit()

    clone = _split_off(s, item, 30)
    s.commit()

    assert (item.quantity, clone.quantity) == (70, 30)
    s.close()
