"""
Per-user price tracking collector (hourly).

For every user's tracked (item × favourite place) it stores a buy/sell/volume
snapshot. Region/system places use Fuzzwork region aggregates; places flagged
`special_parser` (e.g. C-J) use the appraise.gnf.lt local-market scraper.
"""
import logging
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from app.core.database import SessionLocal, TrackedPlace, TrackedItem, TrackPrice

logger = logging.getLogger(__name__)

_AGG_URL = "https://market.fuzzwork.co.uk/aggregates/"
_GNF_REGION = "C-J6MT"
_HEADERS = {"User-Agent": "IndyOps/1.0 (price tracker)"}
_TIMEOUT = 25


def _fuzzwork(region_id: int, type_ids: list[int]) -> dict:
    if not type_ids:
        return {}
    try:
        r = requests.get(_AGG_URL, params={"region": region_id, "types": ",".join(map(str, type_ids))},
                         headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning("fuzzwork region %s failed: %s", region_id, exc)
        return {}


def _fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _gnf(type_id: int) -> dict | None:
    """Scrape C-J local buy/sell from appraise.gnf.lt."""
    try:
        resp = requests.get(f"https://appraise.gnf.lt/item/{type_id}", timeout=_TIMEOUT, headers=_HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        tab = soup.find("div", id=_GNF_REGION)
        if not tab:
            return None
        tables = tab.find_all("table")
        if len(tables) < 2:
            return None

        def parse(t):
            out = {}
            for row in t.find_all("tr"):
                th, td = row.find("th"), row.find("td")
                if th and td:
                    raw = td.text.strip().replace(",", "").replace(" ISK", "")
                    out[th.text.strip()] = _fnum(raw)
            return out

        sell = parse(tables[0]); buy = parse(tables[1])
        return {"sell": sell.get("Min") or sell.get("1st Percentile"),
                "buy": buy.get("Max") or buy.get("99th Percentile")}
    except Exception:
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

    region_data = {rid: _fuzzwork(rid, list(tids)) for rid, tids in region_types.items()}
    special_data = {tid: _gnf(tid) for tid in special_types}

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
