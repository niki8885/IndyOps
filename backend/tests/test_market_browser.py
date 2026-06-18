"""
Unit tests for the Market Browser service (app/services/market_browser.py).

These are pure functions — they take ESI order/history lists and SDE lookup
dicts (stations/systems/regions) already resolved by the caller, so there is no
DB or network I/O to monkeypatch. We construct realistic ESI-shaped inputs and
assert on the returned payload structures and their branches (success, empty,
None/missing, fallback).
"""
from datetime import datetime, timezone

import pytest

from app.services import market_browser as mb


# ── fixtures: SDE lookup tables (already resolved by the router) ──────────────

@pytest.fixture
def stations():
    # location_id → station row
    return {60003760: {"name": "Jita IV - Moon 4 - CNAP", "region_id": 10000002,
                       "system_id": 30000142}}


@pytest.fixture
def systems():
    return {
        30000142: {"name": "Jita", "region_id": 10000002, "security": 0.946},
        30000144: {"name": "Perimeter", "region_id": 10000002, "security": 0.95},
    }


@pytest.fixture
def regions():
    return {10000002: "The Forge"}


def _sell(order_id, price, qty, *, location_id=60003760, system_id=30000142,
          issued="2026-06-10T12:00:00Z", duration=90):
    return {
        "order_id": order_id, "price": price, "volume_remain": qty,
        "is_buy_order": False, "location_id": location_id, "system_id": system_id,
        "issued": issued, "duration": duration,
    }


def _buy(order_id, price, qty, *, location_id=60003760, system_id=30000142,
         issued="2026-06-10T12:00:00Z", duration=90, range_="region", min_volume=1):
    return {
        "order_id": order_id, "price": price, "volume_remain": qty,
        "is_buy_order": True, "location_id": location_id, "system_id": system_id,
        "issued": issued, "duration": duration, "range": range_, "min_volume": min_volume,
    }


# ── _parse_issued ─────────────────────────────────────────────────────────────

def test_parse_issued_valid_z_suffix():
    dt = mb._parse_issued("2026-06-10T12:00:00Z")
    assert dt == datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_issued_none_and_empty():
    assert mb._parse_issued(None) is None
    assert mb._parse_issued("") is None


def test_parse_issued_invalid_string():
    assert mb._parse_issued("not-a-date") is None


# ── _resolve_location ─────────────────────────────────────────────────────────

def test_resolve_location_station_hit(stations, systems, regions):
    loc = mb._resolve_location({"location_id": 60003760, "system_id": None},
                               stations, systems, regions)
    assert loc["location"] == "Jita IV - Moon 4 - CNAP"
    assert loc["region"] == "The Forge"
    assert loc["security"] == pytest.approx(0.946)
    assert loc["system_id"] == 30000142


def test_resolve_location_structure_with_known_system(stations, systems, regions):
    # location_id not a station, but system_id resolves → "<system> (structure)"
    loc = mb._resolve_location({"location_id": 1234567890, "system_id": 30000144},
                               stations, systems, regions)
    assert loc["location"] == "Perimeter (structure)"
    assert loc["region"] == "The Forge"
    assert loc["security"] == pytest.approx(0.95)
    assert loc["system_id"] == 30000144


def test_resolve_location_unknown_structure(stations, systems, regions):
    # neither station nor system known → generic label, no region/security
    loc = mb._resolve_location({"location_id": 999, "system_id": 88888},
                               stations, systems, regions)
    assert loc["location"] == "Structure 999"
    assert loc["region"] is None
    assert loc["security"] is None
    assert loc["system_id"] == 88888


# ── build_orders ──────────────────────────────────────────────────────────────

def test_build_orders_sorts_and_summarizes(stations, systems, regions):
    orders = [
        _sell(1, 6.0, 100),
        _sell(2, 5.0, 50),     # cheapest sell → best_sell
        _buy(3, 4.0, 200),     # highest buy → best_buy
        _buy(4, 3.5, 75),
    ]
    out = mb.build_orders(orders, stations, systems, regions, "The Forge")

    # sellers ascending by price
    assert [s["order_id"] for s in out["sellers"]] == [2, 1]
    # buyers descending by price
    assert [b["order_id"] for b in out["buyers"]] == [3, 4]

    summ = out["summary"]
    assert summ["best_sell"] == pytest.approx(5.0)
    assert summ["best_buy"] == pytest.approx(4.0)
    assert summ["spread"] == pytest.approx(1.0)
    assert summ["mid"] == pytest.approx(4.5)
    assert summ["spread_pct"] == pytest.approx(1.0 / 4.5 * 100)
    assert summ["sell_orders"] == 2 and summ["buy_orders"] == 2
    assert summ["sell_volume"] == 150 and summ["buy_volume"] == 275


def test_build_orders_buyer_fields_and_expiry(stations, systems, regions):
    out = mb.build_orders([_buy(10, 4.0, 9, range_="solarsystem", min_volume=5)],
                          stations, systems, regions, "The Forge")
    row = out["buyers"][0]
    assert row["range"] == "solarsystem"
    assert row["min_volume"] == 5
    # issued 2026-06-10 + 90 days = 2026-09-08
    assert row["expires_at"].startswith("2026-09-08T12:00:00")


def test_build_orders_region_fallback_when_location_unknown(stations, systems, regions):
    # unknown structure → loc.region is None, falls back to passed region_name
    out = mb.build_orders([_sell(1, 5.0, 1, location_id=42, system_id=77777)],
                          stations, systems, regions, "Fallback Region")
    assert out["sellers"][0]["region"] == "Fallback Region"


def test_build_orders_no_issued_no_expiry(stations, systems, regions):
    out = mb.build_orders([_sell(1, 5.0, 1, issued=None)],
                          stations, systems, regions, "The Forge")
    assert out["sellers"][0]["expires_at"] is None


def test_build_orders_empty():
    out = mb.build_orders([], {}, {}, {}, None)
    assert out["sellers"] == [] and out["buyers"] == []
    s = out["summary"]
    assert s["best_sell"] is None and s["best_buy"] is None
    assert s["spread"] is None and s["mid"] is None and s["spread_pct"] is None
    assert s["sell_volume"] == 0 and s["buy_volume"] == 0


def test_build_orders_only_sells_has_no_spread(stations, systems, regions):
    out = mb.build_orders([_sell(1, 5.0, 1)], stations, systems, regions, "The Forge")
    assert out["summary"]["best_sell"] == pytest.approx(5.0)
    assert out["summary"]["best_buy"] is None
    assert out["summary"]["spread"] is None and out["summary"]["mid"] is None


def test_build_orders_limit_truncates(stations, systems, regions):
    orders = [_sell(i, float(i + 1), 1) for i in range(5)]
    out = mb.build_orders(orders, stations, systems, regions, "The Forge", limit=2)
    assert len(out["sellers"]) == 2
    # summary counts reflect ALL orders, not just the truncated slice
    assert out["summary"]["sell_orders"] == 5


# ── build_orderbook ───────────────────────────────────────────────────────────

def test_build_orderbook_aggregates_levels_and_cum():
    orders = [
        _sell(1, 5.0, 10), _sell(2, 5.0, 5),   # same ask price → one level, 2 orders
        _sell(3, 6.0, 20),
        _buy(4, 4.0, 30), _buy(5, 3.0, 10),
    ]
    book = mb.build_orderbook(orders)

    # asks ascending, bids descending
    assert [a["price"] for a in book["asks"]] == [5.0, 6.0]
    assert book["asks"][0]["volume"] == 15 and book["asks"][0]["orders"] == 2
    assert book["asks"][0]["cum"] == 15 and book["asks"][1]["cum"] == 35
    assert [b["price"] for b in book["bids"]] == [4.0, 3.0]

    assert book["best_ask"] == pytest.approx(5.0)
    assert book["best_bid"] == pytest.approx(4.0)
    assert book["spread"] == pytest.approx(1.0)
    assert book["mid"] == pytest.approx(4.5)
    assert book["ask_levels"] == 2 and book["bid_levels"] == 2
    assert book["ask_depth"] == 35 and book["bid_depth"] == 40


def test_build_orderbook_skips_none_price():
    orders = [_sell(1, None, 10), _sell(2, 5.0, 4)]
    book = mb.build_orderbook(orders)
    assert len(book["asks"]) == 1 and book["asks"][0]["price"] == pytest.approx(5.0)


def test_build_orderbook_depth_limit():
    orders = [_sell(i, float(i + 1), 1) for i in range(5)]
    book = mb.build_orderbook(orders, depth=2)
    assert len(book["asks"]) == 2
    assert book["ask_levels"] == 5  # level count is pre-truncation


def test_build_orderbook_empty():
    book = mb.build_orderbook([])
    assert book["asks"] == [] and book["bids"] == []
    assert book["best_ask"] is None and book["best_bid"] is None
    assert book["spread"] is None and book["mid"] is None
    assert book["ask_depth"] == 0 and book["bid_depth"] == 0


# ── history_payload ───────────────────────────────────────────────────────────

def _history(n=40, start=100.0):
    """ESI-shaped daily history rows with full fields."""
    rows = []
    for i in range(n):
        p = start + i  # rising trend
        rows.append({
            "date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
            "average": p,
            "highest": p + 2,
            "lowest": p - 2,
            "volume": 1000 + i * 10,
            "order_count": 50 + i,
        })
    return rows


def test_history_payload_full_shape():
    out = mb.history_payload(_history(40), type_id=34, label="Tritanium",
                             region_name="The Forge", window=14)
    assert out["type_id"] == 34
    assert out["label"] == "Tritanium"
    assert out["region_name"] == "The Forge"
    assert out["window"] == 14
    assert len(out["timestamps"]) == 40

    # series block has all the indicator keys, each same length as timestamps
    series = out["series"]
    for key in ("price", "volume", "sma", "ema", "rsi", "macd", "returns",
                "volatility", "tenkan", "kijun", "senkou_a", "senkou_b"):
        assert key in series
        assert len(series[key]) == 40

    stats = out["stats"]
    assert stats["points"] == 40
    assert stats["last"] == pytest.approx(139.0)         # 100 + 39
    assert stats["all_max"] == pytest.approx(139.0)
    assert stats["all_min"] == pytest.approx(100.0)
    assert stats["change_pct"] == pytest.approx((139.0 - 138.0) / 138.0 * 100)
    assert stats["day_high"] == pytest.approx(141.0)     # last highest = 139 + 2
    assert stats["day_low"] == pytest.approx(137.0)      # last lowest = 139 - 2

    # risk + monte carlo present with enough points
    assert set(out["risk"]) == {"var95", "cvar95", "hist_counts", "hist_edges"}
    assert out["montecarlo"] is not None
    assert out["montecarlo"]["horizon"] == 24
    assert out["states"] is not None
    assert len(out["weekday_volume"]) == 7


def test_history_payload_window_floor():
    # window < 2 is clamped up to 2
    out = mb.history_payload(_history(10), 34, "T", "The Forge", window=1)
    assert out["window"] == 2


def test_history_payload_missing_optional_columns():
    # only date + average present → highest/lowest/volume/order_count defaulted
    hist = [{"date": f"2026-01-{i + 1:02d}", "average": 100.0 + i} for i in range(8)]
    out = mb.history_payload(hist, 34, "T", "The Forge", window=5)
    assert out["stats"]["points"] == 8
    # day_high/low and volumes come from absent columns → None
    assert out["stats"]["day_high"] is None
    assert out["stats"]["day_low"] is None
    assert out["stats"]["avg_volume"] is None
    assert out["stats"]["last_volume"] is None
    assert all(v is None for v in out["weekday_volume"]) or out["weekday_volume"] == [None] * 7


def test_history_payload_single_point_prev_equals_last():
    out = mb.history_payload([{"date": "2026-01-01", "average": 50.0}],
                             34, "T", None, window=5)
    assert out["stats"]["last"] == pytest.approx(50.0)
    # prev defaults to last when only one point → change 0
    assert out["stats"]["change_pct"] == pytest.approx(0.0)
    assert out["stats"]["points"] == 1
    # too few points → no monte carlo / no states
    assert out["montecarlo"] is None
    assert out["states"] is None


# ── correlation_payload ───────────────────────────────────────────────────────

def _corr_hist(prices, start="2026-01-01"):
    out = []
    for i, p in enumerate(prices):
        out.append({"date": f"2026-01-{i + 1:02d}", "average": p})
    return out


def test_correlation_payload_matrix_and_to_target():
    # Correlation is computed on pct-change returns, so we drive the returns
    # directly. A has a varied return pattern; B applies the same per-step
    # factors (perfectly correlated returns); C applies the reciprocal factors
    # (perfectly anti-correlated returns).
    factors = [1.05, 0.97, 1.10, 0.92, 1.03, 1.08, 0.95, 1.06, 0.99, 1.04, 0.96]

    def prices(start, fs):
        out = [float(start)]
        for f in fs:
            out.append(out[-1] * f)
        return out

    histories = {
        "A": _corr_hist(prices(100, factors)),
        "B": _corr_hist(prices(200, factors)),                 # same returns
        "C": _corr_hist(prices(300, [1 / f for f in factors])),  # mirror returns
    }
    out = mb.correlation_payload("A", histories)
    assert out["target"] == "A"
    assert set(out["labels"]) == {"A", "B", "C"}
    assert len(out["matrix"]) == 3 and len(out["matrix"][0]) == 3
    assert out["points"] >= 5

    to_t = {row["label"]: row["corr"] for row in out["to_target"]}
    assert set(to_t) == {"B", "C"}
    # B perfectly tracks A's returns; C moves opposite
    assert to_t["B"] == pytest.approx(1.0, abs=1e-3)
    assert to_t["C"] < -0.99
    # to_target sorted highest corr first
    assert out["to_target"][0]["label"] == "B"


def test_correlation_payload_target_missing():
    histories = {"A": _corr_hist([100, 101, 102, 103, 104, 105])}
    out = mb.correlation_payload("ZZZ", histories)
    assert out["target"] == "ZZZ"
    assert out["matrix"] == [] and out["to_target"] == []
    assert out["points"] == 0
    assert out["labels"] == ["A"]


def test_correlation_payload_too_few_series():
    # only one usable series → < 2 frames → empty matrix
    histories = {"A": _corr_hist([100, 101, 102, 103, 104, 105])}
    out = mb.correlation_payload("A", histories)
    assert out["matrix"] == [] and out["points"] == 0
    assert out["labels"] == ["A"]


def test_correlation_payload_skips_empty_and_malformed():
    histories = {
        "A": _corr_hist([100 + i for i in range(8)]),
        "B": _corr_hist([200 + i for i in range(8)]),
        "EMPTY": [],                                  # skipped (falsy)
        "BAD": [{"foo": 1, "bar": 2}],                # skipped (no date/average)
    }
    out = mb.correlation_payload("A", histories)
    assert set(out["labels"]) == {"A", "B"}          # malformed ones dropped
    assert "EMPTY" not in out["labels"]
    assert "BAD" not in out["labels"]


def test_correlation_payload_all_empty():
    out = mb.correlation_payload("A", {"A": [], "B": []})
    assert out["labels"] == [] and out["matrix"] == [] and out["points"] == 0
