"""
Read-through cache for pre-computed analytics payloads (analytics_cache table).

The worker warms the cache after each collection; the API reads it and only
recomputes on a miss / when stale. Keyed by (kind, cache_key, window).
"""
from __future__ import annotations

from app.core.timeutil import utcnow
from typing import Optional

from app.core.database import AnalyticsCache


def get_cached(db, kind: str, cache_key: str, window: int,
               max_age_seconds: Optional[int] = None) -> Optional[dict]:
    """Cached payload, or None on miss / when older than ``max_age_seconds``."""
    row = (
        db.query(AnalyticsCache)
        .filter(AnalyticsCache.kind == kind, AnalyticsCache.cache_key == cache_key,
                AnalyticsCache.window == window)
        .first()
    )
    if not row:
        return None
    if max_age_seconds is not None:
        age = (utcnow() - row.computed_at).total_seconds()
        if age > max_age_seconds:
            return None
    return row.payload


def set_cached(db, kind: str, cache_key: str, window: int, payload: dict) -> None:
    """Upsert a payload (single row per (kind, cache_key, window))."""
    row = (
        db.query(AnalyticsCache)
        .filter(AnalyticsCache.kind == kind, AnalyticsCache.cache_key == cache_key,
                AnalyticsCache.window == window)
        .first()
    )
    now = utcnow()
    if row:
        row.payload = payload
        row.computed_at = now
    else:
        db.add(AnalyticsCache(kind=kind, cache_key=cache_key, window=window,
                              payload=payload, computed_at=now))
    db.commit()
