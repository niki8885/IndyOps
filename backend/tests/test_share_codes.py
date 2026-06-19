"""Short shareable job codes: store/resolve, TTL, capacity eviction, endpoint."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import manufacturing_router as mr
from app.core.database import Base, ShareCode
from app.core.timeutil import utcnow
from app.repositories import share_repo

USER = SimpleNamespace(id=1)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def test_store_and_get_roundtrip(db):
    code = share_repo.store_share(db, "production", {"product_type_id": 9, "runs": 3})
    assert code.isdigit() and len(code) == 8 and code[0] in "1234"
    assert share_repo.get_share(db, code) == {"source": "production", "body": {"product_type_id": 9, "runs": 3}}
    assert share_repo.get_share(db, "deadbeef") is None


def test_prefix_reservation(db):
    # production / chain reserved to a 1–4 leading digit; projects (Indy+PAK) to 9
    assert share_repo.prefix_for("production") == "1234" and share_repo.prefix_for("chain") == "1234"
    assert share_repo.prefix_for("project") == "9" and share_repo.prefix_for("pak") == "9"
    for src, allowed in (("production", "1234"), ("chain", "1234"), ("project", "9"), ("indy", "9")):
        for _ in range(8):
            assert share_repo.store_share(db, src, {"x": 1})[0] in allowed


def test_upsert_keeps_same_code(db):
    code = share_repo.store_share(db, "production", {"x": 1})
    same = share_repo.upsert_share(db, code, "production", {"x": 2})
    assert same == code
    assert share_repo.get_share(db, code)["body"] == {"x": 2}


def test_expired_code_not_returned(db):
    db.add(ShareCode(code="91919191", source="chain", body={"x": 1},
                     expires_at=utcnow() - timedelta(days=1)))
    db.commit()
    assert share_repo.get_share(db, "91919191") is None


def test_endpoint_resolves_and_404s(db):
    code = share_repo.store_share(db, "chain", {"product_type_id": 5})
    out = asyncio.run(mr.get_share_code(code, current_user=USER, db=db))
    assert out["source"] == "chain" and out["body"]["product_type_id"] == 5
    with pytest.raises(Exception):
        asyncio.run(mr.get_share_code("nope", current_user=USER, db=db))


def test_make_share_builds_link_and_survives_failure(db):
    code, url = mr._make_share(db, "production", {"product_type_id": 1}, "https://host.test/")
    assert url == f"https://host.test/manufacturing?job={code}"
    code2, url2 = mr._make_share(db, "production", {"product_type_id": 1}, None)
    assert code2 and url2 is None


def test_make_share_reuse_keeps_code(db):
    code, _ = mr._make_share(db, "production", {"x": 1}, None)
    code2, _ = mr._make_share(db, "production", {"x": 2}, None, reuse_code=code)
    assert code2 == code  # reopening keeps the same code, no new one minted
    assert share_repo.get_share(db, code)["body"] == {"x": 2}
