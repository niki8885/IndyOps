"""Account Orders helpers — expiry/low-volume flags, competitive price status, summary."""
import datetime

import pytest

from app.services import orders as o
from app.services import ratelimit


NOW = datetime.datetime(2026, 6, 24, 12, 0, 0)


# ── classify (highlight flags) ───────────────────────────────────────────────

def test_expires_at_adds_duration_days():
    issued = datetime.datetime(2026, 6, 20, 12, 0, 0)
    assert o.expires_at(issued, 30) == datetime.datetime(2026, 7, 20, 12, 0, 0)
    assert o.expires_at(None, 30) is None
    assert o.expires_at(issued, None) is None


def test_classify_flags_expiring_and_low_volume():
    order = {"issued": datetime.datetime(2026, 6, 23, 12, 0, 0), "duration": 2,
             "volume_remain": 1, "volume_total": 50}
    flags = o.classify(order, NOW)
    assert flags["expiring_soon"] is True           # lapses in ~1 day
    assert flags["low_volume"] is True              # 1/50 = 2%
    assert flags["expires_at"] == datetime.datetime(2026, 6, 25, 12, 0, 0)


def test_classify_healthy_order_has_no_flags():
    order = {"issued": NOW, "duration": 90, "volume_remain": 90, "volume_total": 100}
    flags = o.classify(order, NOW)
    assert flags["expiring_soon"] is False
    assert flags["low_volume"] is False


# ── price_compare (vs the live region book) ──────────────────────────────────

def test_sell_order_cheapest_is_best():
    r = o.price_compare(100.0, is_buy=False, competing_prices=[120.0, 130.0])
    assert r["status"] == "best"
    assert r["best_competitor"] == 120.0
    assert r["difference"] == pytest.approx(-20.0)


def test_sell_order_undercut_is_outbid():
    r = o.price_compare(100.0, is_buy=False, competing_prices=[90.0, 130.0])
    assert r["status"] == "outbid"
    assert r["best_competitor"] == 90.0
    assert r["difference"] == pytest.approx(10.0)   # I'm 10 ISK dearer than the cheapest


def test_buy_order_highest_bid_is_best():
    r = o.price_compare(100.0, is_buy=True, competing_prices=[90.0, 80.0])
    assert r["status"] == "best"
    assert r["best_competitor"] == 90.0


def test_buy_order_outbid_when_someone_bids_higher():
    r = o.price_compare(100.0, is_buy=True, competing_prices=[110.0])
    assert r["status"] == "outbid"
    assert r["difference"] == pytest.approx(-10.0)


def test_no_competition_is_only():
    assert o.price_compare(100.0, False, [])["status"] == "only"


def test_no_price_returns_none_status():
    assert o.price_compare(None, False, [120.0])["status"] is None


# ── summarize ────────────────────────────────────────────────────────────────

def test_summarize_totals_and_distribution():
    sell = [{"price": 10, "volume_remain": 5, "station": "Jita IV", "system": "Jita"}]
    buy = [{"price": 8, "volume_remain": 3, "escrow": 12, "station": "Amarr", "system": "Amarr"}]
    s = o.summarize(sell, buy)
    assert s["sell_count"] == 1 and s["buy_count"] == 1
    assert s["sell_isk"] == 50 and s["buy_isk"] == 24
    assert s["buy_escrow"] == 12
    assert s["remaining_to_cover"] == 12
    assert {g["name"] for g in s["by_station"]} == {"Jita IV", "Amarr"}
    assert s["by_station"][0]["name"] == "Jita IV"   # richest first


# ── rate limit ───────────────────────────────────────────────────────────────

def test_ratelimit_blocks_second_call_within_cooldown():
    uid = 999_001
    ratelimit.check(uid, "unit_test", 60)            # first call passes
    with pytest.raises(ratelimit.CooldownError) as ei:
        ratelimit.check(uid, "unit_test", 60)        # immediate retry blocked
    assert ei.value.retry_after > 0


def test_ratelimit_zero_cooldown_never_blocks():
    uid = 999_002
    ratelimit.check(uid, "free", 0)
    ratelimit.check(uid, "free", 0)                  # no raise


# ── market order slot capacity ───────────────────────────────────────────────

def test_market_order_capacity_base_and_max():
    from app.services import skills
    assert skills.market_order_capacity({}) == 5            # base, no trade skills
    full = {skills.SKILL_TRADE: 5, skills.SKILL_RETAIL: 5,
            skills.SKILL_WHOLESALE: 5, skills.SKILL_TYCOON: 5}
    assert skills.market_order_capacity(full) == 305        # EVE's hard cap
    assert skills.market_order_capacity({skills.SKILL_TRADE: 3}) == 5 + 12
