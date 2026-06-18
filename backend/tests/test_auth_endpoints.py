"""
Auth endpoints (register / login) plus the shared current-user dependency.

Driven the project's no-HTTP way: the async route functions are imported and
called directly against an in-memory SQLite session. Password hashing (bcrypt)
and JWT minting/verification run for real — no network or native binary — using
the ``SECRET_KEY=test-secret`` set in tests/conftest.py at import time.

There is no dedicated ``/me`` route on the router; the "current user" path lives
in ``app.core.security.get_current_user``, so we exercise it end-to-end with a
real token produced by ``login``.
"""
import asyncio

import pytest
from fastapi import HTTPException
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth_router as ar
from app.api.auth_router import UserRegister, UserLogin
from app.core import security
from app.core.config import SECRET_KEY, ALGORITHM
from app.core.database import Base, UserDB


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


PW = "s3cret-pw"           # valid password for seeded test users (not a real credential)
WRONG_PW = "incorrect-pw"  # deliberately non-matching, for the wrong-password test


def _register(db, username="alice", password=PW, email="alice@example.com"):
    return run(ar.register(UserRegister(username=username, password=password, email=email), db=db))


# ── register ──────────────────────────────────────────────────────────────────

def test_register_success_hashes_password(db):
    out = _register(db)
    assert out["status"] == "user created"
    assert out["username"] == "alice"
    assert out["email"] == "alice@example.com"
    assert out["user_id"] is not None

    row = db.query(UserDB).filter(UserDB.username == "alice").first()
    assert row is not None
    # password is stored hashed, not in clear text, and verifies for real
    assert row.hashed_password != PW
    assert ar._verify_password(PW, row.hashed_password) is True
    assert ar._verify_password("wrong", row.hashed_password) is False


def test_register_duplicate_username(db):
    _register(db, username="bob", email="bob@example.com")
    with pytest.raises(HTTPException) as exc:
        _register(db, username="bob", email="other@example.com")
    assert exc.value.status_code == 400
    assert "Username" in exc.value.detail


def test_register_duplicate_email(db):
    _register(db, username="carol", email="dup@example.com")
    with pytest.raises(HTTPException) as exc:
        _register(db, username="carol2", email="dup@example.com")
    assert exc.value.status_code == 400
    assert "Email" in exc.value.detail


# ── login ───────────────────────────────────────────────────────────────────

def test_login_success_returns_token(db):
    _register(db, username="dave", password=PW, email="dave@example.com")
    out = run(ar.login(UserLogin(username="dave", password=PW), db=db))
    assert out["token_type"] == "bearer"
    assert out["username"] == "dave"
    assert out["email"] == "dave@example.com"

    # the JWT is real and carries the user id in the subject claim
    payload = jwt.decode(out["access_token"], SECRET_KEY, algorithms=[ALGORITHM])
    assert payload["sub"] == str(out["user_id"])


def test_login_wrong_password(db):
    _register(db, username="erin", password=PW, email="erin@example.com")
    with pytest.raises(HTTPException) as exc:
        run(ar.login(UserLogin(username="erin", password=WRONG_PW), db=db))
    assert exc.value.status_code == 401


def test_login_unknown_user(db):
    with pytest.raises(HTTPException) as exc:
        run(ar.login(UserLogin(username="ghost", password=PW), db=db))
    assert exc.value.status_code == 401


# ── current-user dependency (the "me" path) ───────────────────────────────────

def test_get_current_user_with_real_login_token(db):
    reg = _register(db, username="frank", password=PW, email="frank@example.com")
    login_out = run(ar.login(UserLogin(username="frank", password=PW), db=db))
    token = login_out["access_token"]

    # get_current_user is a plain def (not async) → call it directly
    user = security.get_current_user(token=token, db=db)
    assert user.id == reg["user_id"]
    assert user.username == "frank"


def test_get_current_user_invalid_token(db):
    with pytest.raises(HTTPException) as exc:
        security.get_current_user(token="not-a-jwt", db=db)
    assert exc.value.status_code == 401


def test_get_current_user_token_without_sub(db):
    token = security.create_access_token({"foo": "bar"})  # no "sub" claim
    with pytest.raises(HTTPException) as exc:
        security.get_current_user(token=token, db=db)
    assert exc.value.status_code == 401


def test_get_current_user_unknown_user_id(db):
    token = security.create_access_token({"sub": "424242"})  # no such row
    with pytest.raises(HTTPException) as exc:
        security.get_current_user(token=token, db=db)
    assert exc.value.status_code == 401
