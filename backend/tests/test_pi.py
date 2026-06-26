"""Unit tests for the pure PI colony summarizer (no DB/network)."""
import datetime

from app.services import pi

NOW = datetime.datetime(2026, 6, 26, 12, 0, 0)

# SDE-ish type info: a storage facility (12000 m³), a launchpad (10000 m³), and two
# commodities with per-unit volumes; the extractor control unit has no capacity.
TYPE_INFO = {
    2541: {"capacity": 12000.0, "volume": 0.0},   # Storage Facility
    2544: {"capacity": 10000.0, "volume": 0.0},    # Launchpad
    2542: {"capacity": 0.0, "volume": 0.0},        # Extractor Control Unit
    2398: {"capacity": 0.0, "volume": 0.38},       # a P1 commodity (0.38 m³)
    2399: {"capacity": 0.0, "volume": 0.38},       # another P1
}


def _extractor(expiry, product=2398):
    return {"type_id": 2542, "extractor_details": {"product_type_id": product,
            "cycle_time": 3600, "qty_per_cycle": 5000}, "expiry_time": expiry}


def test_extracting_when_a_head_is_in_the_future():
    pins = [_extractor("2026-06-27T12:00:00Z"), _extractor("2026-06-26T18:00:00Z", 2399)]
    s = pi.summarize_colony(pins, TYPE_INFO, NOW)
    assert s["has_extractor"] and s["extracting"]
    assert s["extractor_expiry"] == datetime.datetime(2026, 6, 27, 12, 0, 0)  # latest head
    assert s["products"] == [2398, 2399]


def test_stopped_when_all_expiries_passed():
    pins = [_extractor("2026-06-26T06:00:00Z")]
    s = pi.summarize_colony(pins, TYPE_INFO, NOW)
    assert s["has_extractor"] and not s["extracting"]
    assert s["extractor_expiry"] == datetime.datetime(2026, 6, 26, 6, 0, 0)


def test_storage_used_and_capacity():
    pins = [
        {"type_id": 2541, "contents": [{"type_id": 2398, "amount": 10000}]},  # 10000×0.38=3800
        {"type_id": 2544, "contents": [{"type_id": 2399, "amount": 5000}]},   # 5000×0.38=1900
        _extractor("2026-06-27T12:00:00Z"),                                   # no capacity, ignored
    ]
    s = pi.summarize_colony(pins, TYPE_INFO, NOW)
    assert s["storage_capacity"] == 22000.0    # 12000 + 10000
    assert s["storage_used"] == 5700.0         # 3800 + 1900
    assert pi.storage_pct(s["storage_used"], s["storage_capacity"]) == 25.9


def test_storage_pct_handles_zero_capacity():
    assert pi.storage_pct(100.0, 0) is None
    assert pi.storage_pct(0.0, None) is None


def test_no_extractor_colony():
    s = pi.summarize_colony([{"type_id": 2541, "contents": []}], TYPE_INFO, NOW)
    assert not s["has_extractor"] and not s["extracting"]
    assert s["extractor_expiry"] is None and s["products"] == []
