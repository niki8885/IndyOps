"""
Per-user price tracking collector (hourly).

For every user's tracked (item × favourite place) it stores a buy/sell/volume
snapshot. Region/system places use Fuzzwork region aggregates; places flagged
`special_parser` (e.g. C-J) use the appraise.gnf.lt local-market scraper.
"""
import logging
from datetime import datetime, timezone

from app.adapters import market
from app.core.database import SessionLocal, TrackedPlace, TrackedItem, TrackPrice

logger = logging.getLogger(__name__)


def _fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def collect_for_user(db, user_id: int) -> int:
    places = {p.id: p for p in db.query(TrackedPlace).filter(TrackedPlace.user_id == user_id).all()}
    items = db.query(TrackedItem).filter(TrackedItem.user_id == user_id).all()
    if not places or not items:
        return 0

    plan = []                      # (item, place)
    region_types: dict[int, set] = {}
    special_types: set = set()
    for it in items:
        for pid in (it.place_ids or []):
            p = places.get(pid)
            if not p:
                continue
            plan.append((it, p))
            if p.special_parser:
                special_types.add(it.type_id)
            elif p.region_id:
                region_types.setdefault(p.region_id, set()).add(it.type_id)

    region_data = {rid: market.fuzzwork_aggregates_or_empty(rid, list(tids)) for rid, tids in region_types.items()}
    special_data = {tid: market.gnf_local(tid) for tid in special_types}

    now = datetime.now(timezone.utc)
    stored = 0
    for it, p in plan:
        if p.special_parser:
            d = special_data.get(it.type_id)
            buy = d.get("buy") if d else None
            sell = d.get("sell") if d else None
            vol = None
        else:
            e = (region_data.get(p.region_id) or {}).get(str(it.type_id)) or {}
            buy = _fnum((e.get("buy") or {}).get("max"))
            sell = _fnum((e.get("sell") or {}).get("min"))
            vol = _fnum((e.get("sell") or {}).get("volume"))
        if buy is None and sell is None:
            continue
        db.add(TrackPrice(user_id=user_id, type_id=it.type_id, place_id=p.id,
                          timestamp=now, buy=buy, sell=sell, volume=vol))
        stored += 1

    db.commit()
    return stored


def run_tracking_update() -> dict:
    """Collect snapshots for every user that has tracked items."""
    db = SessionLocal()
    summary = {"users": 0, "rows": 0}
    try:
        user_ids = [uid for (uid,) in db.query(TrackedItem.user_id).distinct().all()]
        for uid in user_ids:
            try:
                n = collect_for_user(db, uid)
                summary["users"] += 1
                summary["rows"] += n
            except Exception as exc:
                db.rollback()
                logger.error("tracking collect failed for user %s: %s", uid, exc)
        logger.info("Tracking update: %d rows for %d users", summary["rows"], summary["users"])
    finally:
        db.close()
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_tracking_update())
