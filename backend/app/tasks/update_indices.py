import logging
from dataclasses import asdict
from datetime import datetime, timezone

from app.adapters import market
from app.core.database import SessionLocal, MarketIndexSnapshot
from app.core.indices_data import (
    BASKETS, VOLUME_COMPONENTS, JITA_REGION, PLEX_REGION, PLEX_TYPE_ID,
)
from app.services import indices

logger = logging.getLogger(__name__)


def _sell_price(entry: dict) -> float:
    sell = entry.get("sell", {})
    for k in ("percentile", "min", "weightedAverage"):
        v = sell.get(k)
        if v not in (None, "", "0", 0):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _sell_volume(entry: dict) -> float:
    try:
        return float(entry.get("sell", {}).get("volume") or 0)
    except (TypeError, ValueError):
        return 0.0


def _compute_basket(key: str, basket: list[tuple[int, float]], region: int) -> dict | None:
    type_ids = [t for t, _ in basket]
    try:
        data = market.fuzzwork_aggregates(region, type_ids)
    except Exception as exc:
        logger.warning("index %s: aggregate fetch failed: %s", key, exc)
        return None

    price_index = 0.0
    volume_index = 0.0
    weights, volumes = [], []
    wsum = sum(w for _, w in basket) or 1.0
    for tid, w in basket:
        e = data.get(str(tid)) or {}
        price = _sell_price(e)
        vol = _sell_volume(e)
        nw = w / wsum
        price_index += nw * price
        volume_index += nw * vol
        weights.append(w)
        volumes.append(vol)

    if price_index <= 0:
        return None
    snap = {"price_index": round(price_index, 2), "volume_index": round(volume_index, 2)}
    snap.update(asdict(indices.concentration(weights)))
    snap["liquidity_index"] = indices.liquidity(volumes)
    return snap


def _compute_plex() -> dict | None:
    for region in (PLEX_REGION, JITA_REGION):
        try:
            data = market.fuzzwork_aggregates(region, [PLEX_TYPE_ID])
        except Exception:
            continue
        e = data.get(str(PLEX_TYPE_ID)) or {}
        price = _sell_price(e)
        if price > 0:
            return {
                "price_index": round(price, 2),
                "volume_index": round(_sell_volume(e), 2),
                "top3_share": 1.0, "h_index": 1.0, "entropy": 0.0,
                "liquidity_index": None,
            }
    return None


def _store(db, key: str, snap: dict):
    db.add(MarketIndexSnapshot(
        index_key=key,
        timestamp=datetime.now(timezone.utc),
        price_index=snap.get("price_index"),
        volume_index=snap.get("volume_index"),
        top3_share=snap.get("top3_share"),
        h_index=snap.get("h_index"),
        entropy=snap.get("entropy"),
        liquidity_index=snap.get("liquidity_index"),
    ))


def run_index_update() -> dict:
    """Collect one snapshot for every index. Returns a summary dict."""
    db = SessionLocal()
    summary = {"stored": [], "errors": []}
    try:
        results = {}
        for key, basket in BASKETS.items():
            snap = _compute_basket(key, basket, JITA_REGION)
            if snap:
                results[key] = snap
                _store(db, key, snap)
                summary["stored"].append(key)
            else:
                summary["errors"].append(key)

        plex = _compute_plex()
        if plex:
            _store(db, "plex", plex)
            summary["stored"].append("plex")
        else:
            summary["errors"].append("plex")

        vol_total = sum(results[k]["volume_index"] for k in VOLUME_COMPONENTS
                        if k in results and results[k].get("volume_index"))
        if vol_total:
            _store(db, "volume", {
                "price_index": round(vol_total, 2),
                "volume_index": round(vol_total, 2),
                "top3_share": None, "h_index": None, "entropy": None, "liquidity_index": None,
            })
            summary["stored"].append("volume")

        db.commit()
        logger.info("Index update stored: %s", ", ".join(summary["stored"]) or "nothing")
    except Exception as exc:
        db.rollback()
        logger.error("Index update failed: %s", exc)
        summary["errors"].append(str(exc))
    finally:
        db.close()
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(run_index_update())
