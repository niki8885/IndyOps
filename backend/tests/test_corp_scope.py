"""Corp tracking scope: `_scoped_chars` corp filtering + the per-corp tracked toggle.

The load-bearing privacy property is that a `corp:` scope only ever returns the
requesting user's OWN characters — never another user's — so corp aggregation can't
leak cross-user financials.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import account_router as ar
from app.core.database import Base, LinkedCharacter, CorpTrackingPref

CORP_A, CORP_B = 1000001, 1000002
USER_A = SimpleNamespace(id=1)
USER_B = SimpleNamespace(id=2)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    # user A: one char in corp A, one in corp B; user B: one char in corp A
    session.add_all([
        LinkedCharacter(id=1, user_id=1, character_id=11, character_name="A-in-corpA",
                        corporation_id=CORP_A, is_active=True, status="active"),
        LinkedCharacter(id=2, user_id=1, character_id=12, character_name="A-in-corpB",
                        corporation_id=CORP_B, is_active=True, status="active"),
        LinkedCharacter(id=3, user_id=2, character_id=13, character_name="B-in-corpA",
                        corporation_id=CORP_A, is_active=True, status="active"),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close(); engine.dispose()


def _names(chars):
    return {c.character_name for c in chars}


def test_corp_scope_returns_only_that_corp(db):
    assert _names(ar._scoped_chars(db, USER_A, f"corp:{CORP_A}")) == {"A-in-corpA"}
    assert _names(ar._scoped_chars(db, USER_A, f"corp:{CORP_B}")) == {"A-in-corpB"}


def test_corp_scope_never_crosses_users(db):
    # user A asking for corp A must NOT see user B's char in corp A
    out = ar._scoped_chars(db, USER_A, f"corp:{CORP_A}")
    assert _names(out) == {"A-in-corpA"}
    assert all(c.user_id == 1 for c in out)
    # user B asking for corp A sees only their own
    assert _names(ar._scoped_chars(db, USER_B, f"corp:{CORP_A}")) == {"B-in-corpA"}


def test_all_drops_untracked_corp(db):
    # baseline: both of user A's chars
    assert _names(ar._scoped_chars(db, USER_A, "all")) == {"A-in-corpA", "A-in-corpB"}
    # toggle corp B off → only the corp-A char remains under "all"
    db.add(CorpTrackingPref(user_id=1, corporation_id=CORP_B, tracked=False))
    db.commit()
    assert _names(ar._scoped_chars(db, USER_A, "all")) == {"A-in-corpA"}
    # explicit corp:B scope still returns it (toggle only affects the "all" aggregate)
    assert _names(ar._scoped_chars(db, USER_A, f"corp:{CORP_B}")) == {"A-in-corpB"}


def test_tracked_true_row_is_a_noop(db):
    db.add(CorpTrackingPref(user_id=1, corporation_id=CORP_B, tracked=True))
    db.commit()
    assert _names(ar._scoped_chars(db, USER_A, "all")) == {"A-in-corpA", "A-in-corpB"}


def test_char_with_no_corp_stays_under_all(db):
    db.add(LinkedCharacter(id=4, user_id=1, character_id=14, character_name="A-no-corp",
                           corporation_id=None, is_active=True, status="active"))
    db.add(CorpTrackingPref(user_id=1, corporation_id=CORP_A, tracked=False))
    db.commit()
    assert _names(ar._scoped_chars(db, USER_A, "all")) == {"A-in-corpB", "A-no-corp"}
