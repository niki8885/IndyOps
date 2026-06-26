"""Pure summarization of one EVE planetary-interaction colony (Tracking → PI).

Given the ESI planet-detail ``pins`` and a ``{type_id: {volume, capacity}}`` map from
the SDE, derive the facts the UI + notifications need — is extraction running, when the
last extractor stops, what it produces, and how full the colony's storage is — without
any DB or network access. The sync step (``tasks.update_esi``) builds the type map and
calls this; see [[indyops-service-layering]].

Extractor pins carry ``extractor_details`` (product + cycle) and a pin-level
``expiry_time`` (when that head stops). Storage pins (command center / storage facility /
launchpad) carry a non-zero SDE ``capacity`` (m³) and ``contents`` ([{type_id, amount}]);
used volume = Σ amount × the item's SDE ``volume``.
"""
from __future__ import annotations
import datetime
from typing import Optional


def _parse_dt(value) -> Optional[datetime.datetime]:
    """Parse an ESI ISO timestamp (``...Z``) to a naive UTC datetime, or pass through a
    datetime. None on anything unparseable."""
    if value is None or isinstance(value, datetime.datetime):
        return value
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def summarize_colony(pins: list[dict], type_info: dict, now: datetime.datetime) -> dict:
    """Reduce a colony's pins to ``{extracting, has_extractor, extractor_expiry,
    products, storage_used, storage_capacity}``.

    ``type_info`` maps ``type_id -> {"volume": float, "capacity": float}`` (missing →
    treated as 0). ``extractor_expiry`` is the latest head-stop time (future when running,
    past once idle); ``extracting`` is True iff some head still has a future stop.
    ``products`` is a sorted list of extracted product type_ids."""
    extractors = [p for p in pins if p.get("extractor_details")]
    expiries = [d for p in extractors if (d := _parse_dt(p.get("expiry_time")))]
    active = [d for d in expiries if d > now]

    products = sorted({
        p["extractor_details"].get("product_type_id")
        for p in extractors
        if p.get("extractor_details", {}).get("product_type_id")
    })

    storage_capacity = 0.0
    storage_used = 0.0
    for p in pins:
        info = type_info.get(p.get("type_id")) or {}
        cap = float(info.get("capacity") or 0.0)
        if cap <= 0:
            continue                          # not a storage-capable pin
        storage_capacity += cap
        for c in p.get("contents") or []:
            vol = float((type_info.get(c.get("type_id")) or {}).get("volume") or 0.0)
            storage_used += (c.get("amount") or 0) * vol

    return {
        "has_extractor": bool(extractors),
        "extracting": bool(active),
        "extractor_expiry": max(expiries) if expiries else None,
        "products": products,
        "storage_used": round(storage_used, 2),
        "storage_capacity": round(storage_capacity, 2),
    }


def storage_pct(used: Optional[float], capacity: Optional[float]) -> Optional[float]:
    """Storage fill as a 0–100 percentage, or None when capacity is unknown/zero."""
    if not capacity:
        return None
    return round((used or 0.0) / capacity * 100.0, 1)
