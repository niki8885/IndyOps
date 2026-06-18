"""
Shared pytest fixtures.

The pure-service tests (manufacturing/indicators/risk/indices/allocation/costing)
need none of this — they import only ``app.services.*``. The DB fixtures below
back the repository tests with a throwaway in-memory SQLite SDE database, so no
real Postgres is ever touched.
"""
import os

# database / database_eve build their engines from this at import time, so it
# must be set before any ``app.core.*`` import (incl. the ones just below).
os.environ.setdefault("SQLALCHEMY_DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-secret")
# don't run create_all/run_migrations against the module-level engine on import
os.environ.setdefault("RUN_DB_BOOTSTRAP", "0")

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import (
    Base, AnalyticsCache, MarketIndexSnapshot, TrackPrice,
    TradeCandidate, StationTradeCandidate, TradeTypeStat,
)
from app.core.database_eve import (
    EveBase, EveType, EveActivityProduct, EveActivityMaterial, EveActivityTime, EveBlueprint,
)


@pytest.fixture
def app_engine():
    """Fresh in-memory app database with just the hot/market tables created."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        MarketIndexSnapshot.__table__, TrackPrice.__table__, AnalyticsCache.__table__,
        TradeCandidate.__table__, StationTradeCandidate.__table__, TradeTypeStat.__table__,
    ])
    yield engine
    engine.dispose()


@pytest.fixture
def app_session(app_engine) -> Session:
    session = sessionmaker(bind=app_engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def eve_engine():
    """Fresh in-memory SDE database with all eve_* tables created."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    EveBase.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def eve_session(eve_engine) -> Session:
    session = sessionmaker(bind=eve_engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def query_counter(eve_engine):
    """Counts SQL statements run on eve_engine — for asserting no N+1."""
    class Counter:
        count = 0

        def reset(self):
            self.count = 0

    c = Counter()

    @event.listens_for(eve_engine, "after_cursor_execute")
    def _on_exec(conn, cursor, statement, parameters, context, executemany):
        c.count += 1

    return c


@pytest.fixture
def seed_blueprint(eve_session):
    """
    Insert a minimal manufacturing recipe: blueprint 1000 → product 2000
    (1 unit/run, 600s) from the given materials. Returns a callable.

    ``materials`` = list of (material_type_id, quantity, name, volume).
    """
    def _seed(materials):
        eve_session.add_all([
            EveActivityProduct(type_id=1000, activity_id=1, product_type_id=2000, quantity=1),
            EveActivityTime(type_id=1000, activity_id=1, time=600),
            EveBlueprint(type_id=1000, max_production_limit=10),
            EveType(type_id=1000, type_name="Widget Blueprint", volume=0.01),
            EveType(type_id=2000, type_name="Widget", volume=2.5),
        ])
        for mtid, qty, name, vol in materials:
            eve_session.add(EveActivityMaterial(
                type_id=1000, activity_id=1, material_type_id=mtid, quantity=qty))
            eve_session.add(EveType(type_id=mtid, type_name=name, volume=vol))
        eve_session.commit()
        return {"bp_type_id": 1000, "product_type_id": 2000}

    return _seed
