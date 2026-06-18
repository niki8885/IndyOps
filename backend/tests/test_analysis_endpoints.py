"""
Commodity-index analytics endpoints (app.api.analysis_router): the overview
card list, the immediate-refresh trigger, and the per-index detail with its
read-through analytics cache. Driven the project's no-HTTP way — the async
route functions are called directly against in-memory SQLite with a seeded
session. The native Fortran analytics-engine and the snapshot-collector worker
are monkeypatched on the router module, so no native binary or network runs;
seeded snapshot rows feed market_repo so the real read path is exercised.
"""
import asyncio
import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import analysis_router as ar
from app.core.database import Base, MarketIndexSnapshot

USER = SimpleNamespace(id=1)


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


def _seed_snapshots(db, key="mineral", n=60, base=100.0, step=1.0):
    """Seed ``n`` hourly snapshots oldest→newest with a gently rising price."""
    now = datetime.datetime(2026, 6, 18, 12, 0, 0)
    for i in range(n):
        db.add(MarketIndexSnapshot(
            index_key=key,
            timestamp=now - datetime.timedelta(hours=(n - 1 - i)),
            price_index=base + i * step,
            volume_index=80000.0 + i * 100,
            top3_share=0.42,
            h_index=0.21,
            entropy=1.8,
            liquidity_index=0.9,
        ))
    db.commit()


def _fake_payload(key, label, kind, win):
    """A representative detail payload mirroring index_report.compute_index_payload."""
    return {
        "key": key, "label": label, "kind": kind, "window": win,
        "timestamps": ["2026-06-18T12:00:00"],
        "series": {"price": [100.0], "volume": [80000.0], "sma": [None],
                   "rsi": [None], "macd": [0.0]},
        "stats": {"last": 159.0, "change_pct": 0.63, "volatility": 0.01, "points": 60},
        "risk": {"var95": -0.02, "cvar95": -0.03, "hist_counts": [1], "hist_edges": [0.0, 1.0]},
        "montecarlo": {"p50": 160.0},
        "heatmap": {"weekday": [0]},
        "states": {"current": "calm"},
    }


@pytest.fixture(autouse=True)
def _no_native(monkeypatch):
    """Never touch the Fortran binary: compute returns a canned payload + engine.

    Asserts it was handed a real, non-empty DataFrame so the read path is
    genuinely exercised before the fake takes over.
    """
    calls = []

    def fake_compute(df, key, label, kind, win):
        assert not df.empty and "price" in df.columns
        calls.append((key, win, len(df)))
        return _fake_payload(key, label, kind, win), "python"

    monkeypatch.setattr(ar.analytics_engine, "compute", fake_compute)
    return calls


# ── GET /indices (overview cards) ─────────────────────────────────────────────

def test_list_indices_empty_when_no_snapshots(db):
    out = run(ar.list_indices(current_user=USER, db=db))
    # one card per known index, all with null summaries and zero points
    assert [c["key"] for c in out["indices"]] == ar.INDEX_ORDER
    for card in out["indices"]:
        assert card["last_price"] is None
        assert card["change_pct"] is None
        assert card["points"] == 0
        assert card["updated_at"] is None
    # labels/kinds come straight from the metadata
    mineral = next(c for c in out["indices"] if c["key"] == "mineral")
    assert mineral["label"] == "Minerals" and mineral["kind"] == "basket"


def test_list_indices_summarises_latest_and_change(db):
    # two points: prev=100, last=110 → +10%
    now = datetime.datetime(2026, 6, 18, 12, 0, 0)
    db.add_all([
        MarketIndexSnapshot(index_key="mineral", timestamp=now - datetime.timedelta(hours=1),
                            price_index=100.0, volume_index=5000.0),
        MarketIndexSnapshot(index_key="mineral", timestamp=now,
                            price_index=110.0, volume_index=6000.0),
    ])
    db.commit()

    out = run(ar.list_indices(current_user=USER, db=db))
    mineral = next(c for c in out["indices"] if c["key"] == "mineral")
    assert mineral["last_price"] == pytest.approx(110.0)
    assert mineral["last_volume"] == pytest.approx(6000.0)
    assert mineral["change_pct"] == pytest.approx(10.0)
    assert mineral["points"] == 2
    assert mineral["updated_at"] == now.isoformat()
    # other indices remain empty
    assert next(c for c in out["indices"] if c["key"] == "ice")["points"] == 0


def test_list_indices_single_point_has_no_change(db):
    _seed_snapshots(db, key="plex", n=1, base=50.0)
    out = run(ar.list_indices(current_user=USER, db=db))
    plex = next(c for c in out["indices"] if c["key"] == "plex")
    assert plex["points"] == 1
    assert plex["last_price"] == pytest.approx(50.0)
    assert plex["change_pct"] is None  # need >=2 points for a delta


# ── POST /refresh ──────────────────────────────────────────────────────────────

def test_refresh_now_delegates_to_collector(db, monkeypatch):
    sentinel = {"stored": ["mineral", "plex"], "errors": []}
    monkeypatch.setattr(ar, "run_index_update", lambda: sentinel)
    out = run(ar.refresh_now(current_user=USER))
    assert out == sentinel


# ── GET /index/{key} ────────────────────────────────────────────────────────────

def test_index_detail_unknown_key_404(db):
    with pytest.raises(ar.HTTPException) as ei:
        run(ar.index_detail(key="nope", current_user=USER, db=db))
    assert ei.value.status_code == 404


def test_index_detail_empty_when_no_snapshots(db):
    out = run(ar.index_detail(key="mineral", current_user=USER, db=db))
    assert out == {"key": "mineral", "label": "Minerals", "empty": True}


def test_index_detail_computes_and_caches(db, _no_native):
    _seed_snapshots(db, key="mineral", n=60)

    out = run(ar.index_detail(key="mineral", window=10, current_user=USER, db=db))
    # payload carries the analytics blocks + the engine label the router attaches
    assert out["key"] == "mineral" and out["label"] == "Minerals"
    assert out["window"] == 10
    assert out["engine"] == "python"
    for block in ("series", "stats", "risk", "montecarlo", "heatmap", "states", "timestamps"):
        assert block in out
    assert "rsi" in out["series"] and "macd" in out["series"]
    assert "var95" in out["risk"]
    assert _no_native == [("mineral", 10, 60)]  # compute ran once, got all 60 rows

    # second call (default refresh=False) is served from the cache → no recompute
    again = run(ar.index_detail(key="mineral", window=10, current_user=USER, db=db))
    assert again["key"] == "mineral" and again["engine"] == "python"
    assert len(_no_native) == 1  # still just the one compute


def test_index_detail_refresh_bypasses_cache(db, _no_native):
    _seed_snapshots(db, key="ice", n=40)

    run(ar.index_detail(key="ice", window=10, current_user=USER, db=db))
    assert len(_no_native) == 1
    # refresh=True recomputes even though a fresh cache entry exists
    run(ar.index_detail(key="ice", window=10, refresh=True, current_user=USER, db=db))
    assert len(_no_native) == 2


def test_index_detail_window_floored_to_two(db, _no_native):
    _seed_snapshots(db, key="pi", n=30)
    out = run(ar.index_detail(key="pi", window=1, current_user=USER, db=db))
    # window<2 is clamped to 2 by the router before compute / cache key
    assert out["window"] == 2
    assert _no_native[0][1] == 2
