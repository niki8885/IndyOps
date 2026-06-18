"""
Persistence for the trade optimizer data layer.

Upserts are dialect-aware: on Postgres they use a bulk INSERT ... ON CONFLICT DO
UPDATE (mirrors :mod:`app.tasks.update_esi`); on other engines (the in-memory
SQLite used by tests) they fall back to per-row ``Session.merge``. Callers are
expected to set ``updated_at`` / ``computed_at`` on every row so the timestamp
advances deterministically each run.
"""
from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import TradeCandidate, StationTradeCandidate, TradeTypeStat

_CHUNK = 1000


def _chunks(rows, n=_CHUNK):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def _upsert(db, model, rows: list[dict], conflict_cols: list[str]) -> int:
    """Upsert ``rows`` keyed by ``conflict_cols``; commits. No-op on empty input."""
    if not rows:
        return 0
    if db.get_bind().dialect.name == "postgresql":
        update_cols = [c.name for c in model.__table__.columns if c.name not in conflict_cols]
        for batch in _chunks(rows):
            stmt = pg_insert(model).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=conflict_cols,
                set_={c: stmt.excluded[c] for c in update_cols},
            )
            db.execute(stmt)
    else:
        for row in rows:
            db.merge(model(**row))
    db.commit()
    return len(rows)


def upsert_trade_candidates(db, rows: list[dict]) -> int:
    return _upsert(db, TradeCandidate, rows, ["item_id", "buy_hub", "sell_hub"])


def upsert_station_candidates(db, rows: list[dict]) -> int:
    return _upsert(db, StationTradeCandidate, rows, ["item_id", "hub"])


def upsert_type_stats(db, rows: list[dict]) -> int:
    return _upsert(db, TradeTypeStat, rows, ["region_id", "type_id"])


def distinct_candidate_type_ids(db) -> list[int]:
    """Distinct type_ids currently present in trade_candidates (history-job universe)."""
    return [r[0] for r in db.query(TradeCandidate.item_id).distinct().all()]


def load_type_stats(db, region_id: int, type_ids: list[int]) -> dict[int, dict]:
    """{type_id: {daily_volume, volatility_cv, sample_days}} for one region."""
    if not type_ids:
        return {}
    rows = (
        db.query(TradeTypeStat)
        .filter(TradeTypeStat.region_id == region_id, TradeTypeStat.type_id.in_(type_ids))
        .all()
    )
    return {
        r.type_id: {
            "daily_volume": r.daily_volume,
            "volatility_cv": r.volatility_cv,
            "sample_days": r.sample_days,
        }
        for r in rows
    }
