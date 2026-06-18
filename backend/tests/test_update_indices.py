"""
Unit tests for the index-collector job (``app.tasks.update_indices``).

Driven against in-memory SQLite the project's no-network way: ``market.fuzzwork_*``
is monkeypatched so no HTTP is touched, and the task's own ``SessionLocal`` is
patched to hand back a seeded in-memory session. We then call the job/helper
functions directly and assert the ``MarketIndexSnapshot`` rows written + the
summary dict returned.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, MarketIndexSnapshot
from app.core.indices_data import PLEX_TYPE_ID, PLEX_REGION, JITA_REGION
from app.tasks import update_indices as ui


def _mem_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[MarketIndexSnapshot.__table__])
    return sessionmaker(bind=engine)(), engine


@pytest.fixture
def db():
    session, engine = _mem_session()
    yield session
    session.close()
    engine.dispose()


def _agg(price, volume):
    """One Fuzzwork aggregate entry with a usable sell price + volume."""
    return {"sell": {"min": price, "volume": volume}, "buy": {"max": price * 0.9}}


# ── small helper coverage ─────────────────────────────────────────────────────

def test_sell_price_prefers_percentile_then_falls_through():
    assert ui._sell_price({"sell": {"percentile": "10.5", "min": "1"}}) == pytest.approx(10.5)
    assert ui._sell_price({"sell": {"percentile": 0, "min": "7"}}) == pytest.approx(7.0)  # skips zero
    assert ui._sell_price({"sell": {}}) == pytest.approx(0.0)
    assert ui._sell_price({}) == pytest.approx(0.0)


def test_sell_volume_parses_and_defaults():
    assert ui._sell_volume({"sell": {"volume": "1234"}}) == pytest.approx(1234.0)
    assert ui._sell_volume({"sell": {"volume": None}}) == pytest.approx(0.0)
    assert ui._sell_volume({"sell": {"volume": "oops"}}) == pytest.approx(0.0)


# ── _compute_basket ───────────────────────────────────────────────────────────

def test_compute_basket_success(monkeypatch):
    basket = [(34, 0.6), (35, 0.4)]
    monkeypatch.setattr(ui.market, "fuzzwork_aggregates",
                        lambda region, ids: {"34": _agg(5.0, 100), "35": _agg(10.0, 200)})
    snap = ui._compute_basket("mineral", basket, JITA_REGION)
    # weighted price = 0.6*5 + 0.4*10 = 7.0
    assert snap["price_index"] == pytest.approx(7.0)
    assert snap["volume_index"] == pytest.approx(0.6 * 100 + 0.4 * 200)
    # concentration + liquidity keys present
    assert {"top3_share", "h_index", "entropy", "liquidity_index"} <= set(snap)


def test_compute_basket_returns_none_on_zero_price(monkeypatch):
    monkeypatch.setattr(ui.market, "fuzzwork_aggregates",
                        lambda region, ids: {"34": _agg(0.0, 0), "35": {}})
    assert ui._compute_basket("mineral", [(34, 1.0), (35, 1.0)], JITA_REGION) is None


def test_compute_basket_returns_none_on_adapter_error(monkeypatch):
    def boom(region, ids):
        raise RuntimeError("fuzzwork down")
    monkeypatch.setattr(ui.market, "fuzzwork_aggregates", boom)
    assert ui._compute_basket("ice", [(34, 1.0)], JITA_REGION) is None


# ── _compute_plex ─────────────────────────────────────────────────────────────

def test_compute_plex_success(monkeypatch):
    monkeypatch.setattr(ui.market, "fuzzwork_aggregates",
                        lambda region, ids: {str(PLEX_TYPE_ID): _agg(4_000_000.0, 50)})
    snap = ui._compute_plex()
    assert snap["price_index"] == pytest.approx(4_000_000.0)
    assert snap["top3_share"] == pytest.approx(1.0) and snap["liquidity_index"] is None


def test_compute_plex_falls_back_to_jita(monkeypatch):
    # PLEX region raises, Jita region has the price → fallback path
    def fetch(region, ids):
        if region == PLEX_REGION:
            raise RuntimeError("empty plex region")
        return {str(PLEX_TYPE_ID): _agg(3_500_000.0, 10)}
    monkeypatch.setattr(ui.market, "fuzzwork_aggregates", fetch)
    snap = ui._compute_plex()
    assert snap["price_index"] == pytest.approx(3_500_000.0)


def test_compute_plex_none_when_no_price(monkeypatch):
    monkeypatch.setattr(ui.market, "fuzzwork_aggregates", lambda region, ids: {})
    assert ui._compute_plex() is None


# ── run_index_update (the job entry point) ────────────────────────────────────

def test_run_index_update_success(monkeypatch, db):
    monkeypatch.setattr(ui, "SessionLocal", lambda: db)
    # every basket + plex resolves to the same priced aggregate
    monkeypatch.setattr(ui.market, "fuzzwork_aggregates",
                        lambda region, ids: {str(t): _agg(5.0, 100) for t in ids})

    summary = ui.run_index_update()

    # 4 baskets + plex + the synthetic volume index all stored
    assert set(summary["stored"]) == {"mineral", "ice", "pi", "moon", "plex", "volume"}
    assert summary["errors"] == []

    keys = {r.index_key for r in db.query(MarketIndexSnapshot).all()}
    assert keys == {"mineral", "ice", "pi", "moon", "plex", "volume"}
    # the synthetic volume row sums the four component volume_index values
    vol_row = db.query(MarketIndexSnapshot).filter_by(index_key="volume").one()
    assert vol_row.price_index == pytest.approx(vol_row.volume_index)
    assert vol_row.volume_index > 0


def test_run_index_update_all_empty(monkeypatch, db):
    monkeypatch.setattr(ui, "SessionLocal", lambda: db)
    monkeypatch.setattr(ui.market, "fuzzwork_aggregates", lambda region, ids: {})

    summary = ui.run_index_update()

    # nothing priced → every basket + plex lands in errors, no volume row
    assert summary["stored"] == []
    assert set(summary["errors"]) == {"mineral", "ice", "pi", "moon", "plex"}
    assert db.query(MarketIndexSnapshot).count() == 0


def test_run_index_update_handles_store_exception(monkeypatch, db):
    monkeypatch.setattr(ui, "SessionLocal", lambda: db)
    monkeypatch.setattr(ui.market, "fuzzwork_aggregates",
                        lambda region, ids: {str(t): _agg(5.0, 100) for t in ids})
    # blow up inside the try-block so the rollback/except branch records the error
    monkeypatch.setattr(ui, "_compute_basket",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("compute boom")))

    summary = ui.run_index_update()
    assert any("compute boom" in e for e in summary["errors"])
