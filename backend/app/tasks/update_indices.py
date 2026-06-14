"""
Hourly commodity-index collector.

Fetches Fuzzwork market aggregates for each basket, computes a volume-weighted
price index + volume index + concentration / liquidity metrics, and stores one
MarketIndexSnapshot row per index. The Volume index is synthesised from the
combined throughput of the mineral/ice/pi/moon sub-indices.
"""
import logging
import math
from datetime import datetime, timezone

import requests

from app.core.database import SessionLocal, MarketIndexSnapshot
from app.core.indices_data import (
    BASKETS, VOLUME_COMPONENTS, JITA_REGION, PLEX_REGION, PLEX_TYPE_ID,
)

logger = logging.getLogger(__name__)

_AGG_URL = "https://market.fuzzwork.co.uk/aggregates/"
_HEADERS = {"User-Agent": "IndyOps/1.0 (industry analytics)"}
_TIMEOUT = 30


def _fetch_aggregates(region: int, type_ids: list[int]) -> dict:
    """Return Fuzzwork aggregate data keyed by type_id (str)."""
    if not type_ids:
        return {}
    ids = ",".join(str(t) for t in type_ids)
    resp = requests.get(_AGG_URL, params={"region": region, "types": ids}, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


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


def _concentration(weights: list[float]) -> dict:
    ws = [w for w in weights if w > 0]
    total = sum(ws) or 1.0
    norm = [w / total for w in ws]
    top3 = sum(sorted(norm, reverse=True)[:3])
    h = sum(w * w for w in norm)
    entropy = -sum(w * math.log(w) for w in norm if w > 0)
    return {"top3_share": round(top3, 6), "h_index": round(h, 6), "entropy": round(entropy, 6)}


def _liquidity(volumes: list[float]) -> float | None:
    vs = [v for v in volumes if v and v > 0]
    if len(vs) < 2:
        return None
    mean = sum(vs) / len(vs)
    var = sum((v - mean) ** 2 for v in vs) / len(vs)
    std = math.sqrt(var)
    return round(mean / std, 4) if std else None


def _compute_basket(key: str, basket: list[tuple[int, float]], region: int) -> dict | None:
    type_ids = [t for t, _ in basket]
    try:
        data = _fetch_aggregates(region, type_ids)
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
    snap.update(_concentration(weights))
    snap["liquidity_index"] = _liquidity(volumes)
    return snap


def _compute_plex() -> dict | None:
    for region in (PLEX_REGION, JITA_REGION):
        try:
            data = _fetch_aggregates(region, [PLEX_TYPE_ID])
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
