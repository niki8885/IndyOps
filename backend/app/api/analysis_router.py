"""
Commodity-index analytics endpoints.

The heavy compute lives in app.services.index_report; rows come columnar from
app.repositories.market_repo; results are served from analytics_cache
(read-through, recompute on miss/stale). The hourly worker warms the cache.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db, MarketIndexSnapshot, UserDB
from app.core.indices_data import INDEX_META, INDEX_ORDER
from app.core.security import get_current_user
from app.repositories import cache_repo, market_repo
from app.services import index_report
from app.services._numeric import clean
from app.tasks.update_indices import run_index_update

router = APIRouter()

_CACHE_TTL = 3600   # serve cached detail for up to an hour (matches the hourly collector)


@router.get("/indices")
async def list_indices(
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """All indices with a small latest-summary for the overview cards."""
    out = []
    for key in INDEX_ORDER:
        meta = INDEX_META[key]
        rows = (
            db.query(MarketIndexSnapshot)
            .filter(MarketIndexSnapshot.index_key == key)
            .order_by(MarketIndexSnapshot.timestamp.desc())
            .limit(48)
            .all()
        )
        last = rows[0] if rows else None
        prev = rows[1] if len(rows) > 1 else None
        change = None
        if last and prev and prev.price_index:
            change = (last.price_index - prev.price_index) / prev.price_index * 100
        out.append({
            "key": key,
            "label": meta["label"],
            "kind": meta["kind"],
            "last_price": clean(last.price_index) if last else None,
            "last_volume": clean(last.volume_index) if last else None,
            "change_pct": clean(change),
            "points": len(rows),
            "updated_at": last.timestamp.isoformat() if last else None,
        })
    return {"indices": out}


@router.post("/refresh")
async def refresh_now(current_user: UserDB = Depends(get_current_user)):
    """Collect a snapshot immediately (instead of waiting for the hourly job)."""
    return run_index_update()


@router.get("/index/{key}")
async def index_detail(
        key: str,
        window: int = 10,
        days: int = 60,
        refresh: bool = False,
        current_user: UserDB = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    if key not in INDEX_META:
        raise HTTPException(404, "Unknown index")

    win = max(2, int(window))
    if not refresh:
        cached = cache_repo.get_cached(db, "index", key, win, max_age_seconds=_CACHE_TTL)
        if cached is not None:
            return cached

    df = market_repo.index_snapshots_df(db, key)
    if df.empty:
        return {"key": key, "label": INDEX_META[key]["label"], "empty": True}

    payload = index_report.compute_index_payload(
        df, key, INDEX_META[key]["label"], INDEX_META[key]["kind"], win)
    cache_repo.set_cached(db, "index", key, win, payload)
    return payload
