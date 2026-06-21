"""
Persistence for the trade optimizer data layer.

Upserts are dialect-aware: on Postgres they use a bulk INSERT ... ON CONFLICT DO
UPDATE (mirrors :mod:`app.tasks.update_esi`); on other engines (the in-memory
SQLite used by tests) they fall back to per-row ``Session.merge``. Callers are
expected to set ``updated_at`` / ``computed_at`` on every row so the timestamp
advances deterministically each run.
"""
from __future__ import annotations

from sqlalchemy import func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import (
    TradeCandidate, StationTradeCandidate, TradeTypeStat, HaulCandidate,
)

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


def query_candidates(db, *, buy_stations: list[int] | None = None,
                     sell_stations: list[int] | None = None,
                     max_buy_price: float | None = None, max_volume: float | None = None,
                     min_margin: float = 0.0, strategy: str = "patient",
                     limit: int = 50) -> list[TradeCandidate]:
    """Cross-hub candidates filtered by the user's constraints, ranked by
    (chosen-strategy margin · volume_score) descending — the Layer-3 read."""
    margin_col = (TradeCandidate.margin_pct_instant if strategy == "instant"
                  else TradeCandidate.margin_pct_patient)
    q = db.query(TradeCandidate).filter(margin_col.isnot(None), margin_col >= min_margin)
    if buy_stations:
        q = q.filter(TradeCandidate.buy_hub.in_(buy_stations))
    if sell_stations:
        q = q.filter(TradeCandidate.sell_hub.in_(sell_stations))
    if max_buy_price is not None:
        q = q.filter(TradeCandidate.buy_price <= max_buy_price)
    if max_volume is not None:
        q = q.filter(TradeCandidate.item_volume_m3 <= max_volume)
    return q.order_by((margin_col * TradeCandidate.volume_score).desc()).limit(limit).all()


def query_station_candidates(db, *, stations: list[int] | None = None,
                             min_margin: float = 0.0, limit: int = 50) -> list[StationTradeCandidate]:
    """In-station flips filtered by hub, ranked by (margin · volume_score) desc."""
    q = db.query(StationTradeCandidate).filter(
        StationTradeCandidate.margin_pct.isnot(None),
        StationTradeCandidate.margin_pct >= min_margin,
    )
    if stations:
        q = q.filter(StationTradeCandidate.hub.in_(stations))
    return q.order_by(
        (StationTradeCandidate.margin_pct * StationTradeCandidate.volume_score).desc()
    ).limit(limit).all()


def latest_updated_at(db, model):
    """Newest updated_at across a candidate table (for the TTL freshness check)."""
    return db.query(func.max(model.updated_at)).scalar()


def liquid_type_ids(db, region_id: int, min_volume: float, limit: int) -> list[tuple[int, float]]:
    """The most-liquid types in one region from trade_type_stats: ``[(type_id,
    daily_volume)]`` with ``daily_volume >= min_volume``, ordered desc, capped to
    ``limit``. Drives the haul scanner's bounded Jita universe."""
    rows = (
        db.query(TradeTypeStat.type_id, TradeTypeStat.daily_volume)
        .filter(TradeTypeStat.region_id == region_id,
                TradeTypeStat.daily_volume.isnot(None),
                TradeTypeStat.daily_volume >= min_volume)
        .order_by(TradeTypeStat.daily_volume.desc())
        .limit(limit)
        .all()
    )
    return [(tid, float(dv)) for tid, dv in rows]


def replace_haul_candidates(db, rows: list[dict]) -> int:
    """Full-snapshot refresh of haul_candidates (delete-all + bulk insert); commits.
    The table is small and current-state, so a clean replace beats prune-stale logic."""
    db.query(HaulCandidate).delete()
    if rows:
        db.bulk_insert_mappings(HaulCandidate, rows)
    db.commit()
    return len(rows)


def query_haul_candidates(db, *, min_margin: float = 0.0, method: str | None = None,
                          category_id: int | None = None, group_ids: list[int] | None = None,
                          meta_groups: set[int] | None = None, type_ids: list[int] | None = None,
                          rank_by: str = "profit", limit: int = 100) -> list[HaulCandidate]:
    """Profitable Jita → C-J haul candidates, ranked by per-unit profit or ROI desc.

    ``group_ids`` filters by SDE group (the Drugs bucket) instead of ``category_id``.
    ``meta_groups`` keeps only those tech-level meta groups; a NULL meta_group_id is
    treated as Tech I (1). ``type_ids`` restricts to an explicit set (portfolio reads)."""
    q = db.query(HaulCandidate).filter(
        HaulCandidate.margin_pct.isnot(None), HaulCandidate.margin_pct >= min_margin)
    if method:
        q = q.filter(HaulCandidate.best_method == method)
    if type_ids is not None:
        q = q.filter(HaulCandidate.item_id.in_(type_ids or [-1]))
    if group_ids:
        q = q.filter(HaulCandidate.group_id.in_(group_ids))
    elif category_id is not None:
        q = q.filter(HaulCandidate.category_id == category_id)
    if meta_groups:
        conds = [HaulCandidate.meta_group_id.in_(list(meta_groups))]
        if 1 in meta_groups:                       # Tech I also covers the no-meta-row items
            conds.append(HaulCandidate.meta_group_id.is_(None))
        q = q.filter(or_(*conds))
    order = HaulCandidate.margin_pct if rank_by == "roi" else HaulCandidate.profit_per_unit
    return q.order_by(order.desc()).limit(limit).all()


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
