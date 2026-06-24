"""
Persistence for precomputed market forecasts (IO-49).

The ``forecasts`` worker upserts one row per (region, type, horizon); the
/market/forecast endpoint reads the freshest row and serves its stored payload,
falling back to an on-demand compute on a miss/stale. Upsert is dialect-aware
(Postgres ON CONFLICT, else per-row merge), mirroring app.repositories.trade_repo.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import MarketForecast, utcnow

_CONFLICT = ["region_id", "type_id", "horizon"]


def upsert_forecasts(db, rows: list[dict]) -> int:
    """Upsert forecast rows keyed by (region_id, type_id, horizon); commits."""
    if not rows:
        return 0
    if db.get_bind().dialect.name == "postgresql":
        update_cols = [c.name for c in MarketForecast.__table__.columns
                       if c.name not in _CONFLICT]
        stmt = pg_insert(MarketForecast).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=_CONFLICT,
            set_={c: stmt.excluded[c] for c in update_cols},
        )
        db.execute(stmt)
    else:
        for row in rows:
            db.merge(MarketForecast(**row))
    db.commit()
    return len(rows)


def get_forecast(db, region_id: int, type_id: int, horizon: int,
                 max_age_seconds: int | None = None) -> dict | None:
    """Stored forecast payload for (region, type, horizon), or None if absent/stale."""
    row = db.get(MarketForecast, (region_id, type_id, horizon))
    if row is None:
        return None
    if max_age_seconds is not None and row.computed_at is not None:
        if utcnow() - row.computed_at > timedelta(seconds=max_age_seconds):
            return None
    return row.payload
