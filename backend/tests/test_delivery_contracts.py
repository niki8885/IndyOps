"""Delivery ↔ ESI-contract reconciliation (auto-complete on finished + tracked flag)."""
import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deliveries_router import _match_contracts, _annotate, _apply_complete
from app.core.database import (
    Base, Delivery, DeliveryStatusEvent, InventoryItem, EsiContract, LinkedCharacter,
)

CODE = "ABC1234567"
TITLE = f"Fuel Blocks | 2026-06-17 | {CODE} | -> RYC-19"


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[
        Delivery.__table__, DeliveryStatusEvent.__table__, InventoryItem.__table__,
        EsiContract.__table__, LinkedCharacter.__table__,
    ])
    return sessionmaker(bind=engine)()


def _link(s, user_id=1, character_id=100):
    s.add(LinkedCharacter(user_id=user_id, character_id=character_id, character_name="Sender"))


def _contract(s, status, character_id=100, contract_id=1, title=TITLE):
    s.add(EsiContract(character_id=character_id, contract_id=contract_id,
                      title=title, status=status, type="courier",
                      date_issued=datetime.datetime(2026, 6, 17)))


def test_match_contracts_by_code_in_title():
    s = _session()
    _link(s)
    _contract(s, "outstanding")
    s.commit()
    m = _match_contracts(s, 1, [CODE, "ZZZ0000000"])
    assert CODE in m and len(m[CODE]) == 1
    assert "ZZZ0000000" not in m
    s.close()


def test_no_linked_characters_means_no_match():
    s = _session()
    _contract(s, "finished")          # contract exists but no LinkedCharacter for the user
    s.commit()
    assert _match_contracts(s, 1, [CODE]) == {}
    s.close()


def test_annotate_sets_tracked_and_status():
    s = _session()
    _link(s)
    _contract(s, "outstanding")
    s.commit()
    d = Delivery(user_id=1, code=CODE, status="pending")
    s.add(d); s.commit()
    _annotate(d, _match_contracts(s, 1, [CODE]))
    assert d.tracked is True
    assert d.contract_status == "outstanding"
    s.close()


def test_annotate_prefers_finished_among_duplicates():
    s = _session()
    _link(s)
    _contract(s, "deleted", contract_id=1)
    _contract(s, "finished", contract_id=2)   # a remade contract that completed
    s.commit()
    d = Delivery(user_id=1, code=CODE, status="pending")
    s.add(d); s.commit()
    _annotate(d, _match_contracts(s, 1, [CODE]))
    assert d.contract_status == "finished"
    s.close()


def test_apply_complete_moves_items_to_target():
    s = _session()
    d = Delivery(user_id=1, code=CODE, status="pending", target_place="RYC-19")
    s.add(d); s.flush()
    s.add(InventoryItem(user_id=1, name="Fuel Block", quantity=90_000,
                        place="Jita", delivery_id=d.id))
    s.commit()

    _apply_complete(s, d, datetime.datetime.now(datetime.timezone.utc))
    s.commit()

    assert d.status == "completed"
    assert d.completed_at is not None
    lot = s.query(InventoryItem).first()
    assert lot.place == "RYC-19"
    assert lot.delivery_id is None
    s.close()


def test_apply_complete_records_status_event():
    s = _session()
    d = Delivery(user_id=1, code=CODE, status="pending",
                 source_place="Jita", target_place="RYC-19")
    s.add(d); s.flush()
    _apply_complete(s, d, datetime.datetime.now(datetime.timezone.utc))
    s.commit()

    events = s.query(DeliveryStatusEvent).filter(
        DeliveryStatusEvent.delivery_id == d.id).all()
    assert len(events) == 1
    assert events[0].status == "completed"
    assert events[0].from_status == "pending"
    assert "RYC-19" in (events[0].note or "")
    s.close()


def test_untracked_delivery_has_no_flag():
    s = _session()
    d = Delivery(user_id=1, code="NOPE000000", status="pending")
    s.add(d); s.commit()
    _annotate(d, {})
    assert d.tracked is False and d.contract_status is None
    s.close()
