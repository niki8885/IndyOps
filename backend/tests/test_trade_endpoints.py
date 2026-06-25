"""
Trade optimizer query API (Layer 3) endpoint tests — project no-HTTP style:
import the router and call route coroutines directly with deps as plain args,
against in-memory SQLite seeded with candidate rows. No network is touched
(the router is ESI-free; it only reads the precomputed candidate tables).
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import trade_router as tr
from app.core import config
from app.core.database import (
    Base,
)
from app.core.trade_data import HUB_STATION_IDS

USER = SimpleNamespace(id=1)

JITA = HUB_STATION_IDS["Jita"]
AMARR = HUB_STATION_IDS["Amarr"]
RENS = HUB_STATION_IDS["Rens"]


def run(coro):
    return asyncio.run(coro)


# Route functions declare their query params with FastAPI ``Query(...)`` default
# sentinels. Calling them directly (no HTTP layer to resolve those) means every
# param must be passed explicitly; these wrappers supply the real defaults so a
# test only overrides what it cares about.
def call_candidates(db, **overrides):
    kw = dict(budget=None, cargo=None, buy_hubs=None, sell_hubs=None,
              strategy="patient", min_margin=0.0, limit=50)
    kw.update(overrides)
    return run(tr.list_candidates(current_user=USER, db=db, **kw))


def call_station(db, **overrides):
    kw = dict(hubs=None, budget=None, min_margin=0.0, limit=50)
    kw.update(overrides)
    return run(tr.list_station_candidates(current_user=USER, db=db, **kw))


def call_portfolio(db, **overrides):
    return run(tr.trade_portfolio(body=tr.TradePortfolioRequest(**overrides),
                                  current_user=USER, db=db))


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _route(item_id, buy_hub, sell_hub, *, margin_p=0.20, margin_i=0.10,
           score=0.5, buy_price=100.0, volume_m3=1.0, daily_volume=1000.0,
           ts=None):
    bp = buy_price
    return {
        "item_id": item_id, "buy_hub": buy_hub, "sell_hub": sell_hub,
        "type_name": f"Item{item_id}", "buy_price": bp,
        "sell_price_patient": bp * (1 + margin_p),
        "sell_price_instant": bp * (1 + margin_i),
        "margin_pct_patient": margin_p, "margin_pct_instant": margin_i,
        "profit_isk_patient": bp * margin_p, "profit_isk_instant": bp * margin_i,
        "transport_cost": 0.5, "item_volume_m3": volume_m3,
        "daily_volume": daily_volume, "volatility_cv": 0.05,
        "volume_score": score, "updated_at": ts or datetime(2026, 1, 1),
    }


def _station(item_id, hub, *, margin=0.10, score=0.5, buy_price=90.0,
             sell_price=100.0, daily_volume=1000.0, ts=None):
    return {
        "item_id": item_id, "hub": hub, "type_name": f"Item{item_id}",
        "buy_price": buy_price, "sell_price": sell_price, "margin_pct": margin,
        "profit_isk": sell_price - buy_price, "daily_volume": daily_volume,
        "volatility_cv": 0.05, "volume_score": score,
        "updated_at": ts or datetime(2026, 1, 1),
    }


# --------------------------------------------------------------------------- #
# /hubs
# --------------------------------------------------------------------------- #
def test_list_hubs_returns_all_five_hubs():
    out = run(tr.list_hubs(current_user=USER))
    names = {h["name"] for h in out}
    assert names == {"Jita", "Amarr", "Dodixie", "Rens", "Hek"}
    jita = next(h for h in out if h["name"] == "Jita")
    assert jita["station_id"] == JITA
    assert jita["region_id"] == 10000002


# --------------------------------------------------------------------------- #
# /candidates
# --------------------------------------------------------------------------- #
def test_candidates_success_ranks_and_shapes_rows(db):
    from app.repositories import trade_repo
    trade_repo.upsert_trade_candidates(db, [
        _route(34, JITA, AMARR, margin_p=0.20, score=0.5),   # 0.10
        _route(36, AMARR, JITA, margin_p=0.50, score=0.9),   # 0.45 ← best
        _route(37, JITA, AMARR, margin_p=0.01, score=0.1),   # 0.001 ← worst
    ])
    res = call_candidates(db)
    assert res["strategy"] == "patient"
    assert res["count"] == 3
    assert res["ttl_seconds"] == config.TRADE_TTL_SECONDS
    rows = res["rows"]
    # ranked by patient margin · volume_score desc
    assert rows[0]["item_id"] == 36
    assert rows[-1]["item_id"] == 37
    # human-readable hub names resolved from station_ids
    assert rows[0]["buy_hub"] == "Amarr"
    assert rows[0]["sell_hub"] == "Jita"
    # patient sell_price/margin/profit selected, score = margin · volume_score
    assert rows[0]["margin_pct"] == pytest.approx(0.50)
    assert rows[0]["score"] == pytest.approx(0.50 * 0.9)
    # fresh data seeded at 2026-01-01 is well past TTL → stale True
    assert res["stale"] is True
    assert res["updated_at"] is not None


def test_candidates_instant_strategy_uses_instant_columns(db):
    from app.repositories import trade_repo
    trade_repo.upsert_trade_candidates(db, [
        _route(34, JITA, AMARR, margin_p=0.20, margin_i=0.08, score=1.0),
    ])
    res = call_candidates(db, strategy="instant")
    assert res["strategy"] == "instant"
    r = res["rows"][0]
    assert r["margin_pct"] == pytest.approx(0.08)
    assert r["sell_price"] == pytest.approx(100.0 * 1.08)
    assert r["score"] == pytest.approx(0.08 * 1.0)


def test_candidates_filters_buy_hub_budget_cargo_margin(db):
    from app.repositories import trade_repo
    trade_repo.upsert_trade_candidates(db, [
        _route(34, JITA, AMARR, margin_p=0.20, buy_price=100.0, volume_m3=1.0),
        _route(36, AMARR, JITA, margin_p=0.50, buy_price=5000.0, volume_m3=50.0),
    ])
    # buy_hubs restricts source hub → only the Jita-sourced route
    only_jita = call_candidates(db, buy_hubs="Jita")
    assert [r["item_id"] for r in only_jita["rows"]] == [34]

    # budget excludes the 5,000-ISK item
    affordable = call_candidates(db, budget=1000.0)
    assert [r["item_id"] for r in affordable["rows"]] == [34]

    # cargo excludes the bulky 50 m³ item
    small = call_candidates(db, cargo=10.0)
    assert [r["item_id"] for r in small["rows"]] == [34]

    # margin floor keeps only the high-margin route
    rich = call_candidates(db, min_margin=0.3)
    assert [r["item_id"] for r in rich["rows"]] == [36]


def test_candidates_sell_hub_filter_and_plan_trade_sizing(db):
    from app.repositories import trade_repo
    trade_repo.upsert_trade_candidates(db, [
        _route(34, JITA, AMARR, buy_price=100.0, daily_volume=1000.0),
        _route(35, JITA, RENS, buy_price=100.0, daily_volume=1000.0),
    ])
    # sell_hubs restricts destination hub
    to_amarr = call_candidates(db, sell_hubs="Amarr")
    assert [r["item_id"] for r in to_amarr["rows"]] == [34]

    # with a budget/cargo, plan_trade sizes the trip → units present
    sized = call_candidates(db, sell_hubs="Amarr", budget=500.0, cargo=3.0)
    r = sized["rows"][0]
    # tightest cap: budget 500/100=5, cargo 3/1=3, daily 1000 → 3
    assert r["units"] == 3
    assert r["trip_cost"] == pytest.approx(300.0)


def test_candidates_empty_returns_zero_rows_and_stale(db):
    res = call_candidates(db)
    assert res["count"] == 0
    assert res["rows"] == []
    # no rows → latest_updated_at None → updated_at None, stale True
    assert res["updated_at"] is None
    assert res["stale"] is True


def test_candidates_fresh_data_not_stale(db):
    from app.repositories import trade_repo
    fresh = datetime.now(timezone.utc).replace(tzinfo=None)
    trade_repo.upsert_trade_candidates(db, [_route(34, JITA, AMARR, ts=fresh)])
    res = call_candidates(db)
    assert res["stale"] is False


def test_candidates_limit_caps_rows(db):
    from app.repositories import trade_repo
    trade_repo.upsert_trade_candidates(db, [
        _route(34, JITA, AMARR, margin_p=0.20),
        _route(36, AMARR, JITA, margin_p=0.50),
    ])
    res = call_candidates(db, limit=1)
    assert res["count"] == 1


# --------------------------------------------------------------------------- #
# /station
# --------------------------------------------------------------------------- #
def test_station_success_ranks_and_shapes_rows(db):
    from app.repositories import trade_repo
    trade_repo.upsert_station_candidates(db, [
        _station(34, JITA, margin=0.05, score=0.4),   # 0.020
        _station(35, AMARR, margin=0.30, score=0.9),  # 0.270 ← best
    ])
    res = call_station(db)
    assert res["count"] == 2
    assert res["ttl_seconds"] == config.TRADE_TTL_SECONDS
    rows = res["rows"]
    assert rows[0]["item_id"] == 35
    assert rows[0]["hub"] == "Amarr"
    assert rows[0]["score"] == pytest.approx(0.30 * 0.9)
    assert rows[-1]["item_id"] == 34
    assert res["stale"] is True
    assert res["updated_at"] is not None


def test_station_filters_hub_and_margin(db):
    from app.repositories import trade_repo
    trade_repo.upsert_station_candidates(db, [
        _station(34, JITA, margin=0.05),
        _station(35, AMARR, margin=0.30),
    ])
    jita_only = call_station(db, hubs="Jita")
    assert [r["item_id"] for r in jita_only["rows"]] == [34]

    rich = call_station(db, min_margin=0.2)
    assert [r["item_id"] for r in rich["rows"]] == [35]


def test_station_budget_sizes_trip(db):
    from app.repositories import trade_repo
    trade_repo.upsert_station_candidates(db, [
        _station(34, JITA, buy_price=100.0, sell_price=110.0, daily_volume=1000.0),
    ])
    res = call_station(db, budget=550.0)
    r = res["rows"][0]
    # budget cap 550/100=5, daily 1000 → 5
    assert r["units"] == 5
    assert r["trip_profit"] == pytest.approx(50.0)  # 5 * (110-100)


def test_station_empty_returns_zero_rows_and_stale(db):
    res = call_station(db)
    assert res["count"] == 0
    assert res["rows"] == []
    assert res["updated_at"] is None
    assert res["stale"] is True


# --------------------------------------------------------------------------- #
# helpers: _stations_for / _freshness edge behaviour
# --------------------------------------------------------------------------- #
def test_stations_for_csv_parsing_and_unknown_names():
    assert tr._stations_for(None) is None
    assert tr._stations_for("") is None
    assert tr._stations_for("Jita, Amarr") == [JITA, AMARR]
    # unknown hub names are dropped; all-unknown → None
    assert tr._stations_for("Nowhere") is None
    assert tr._stations_for("Jita, Nowhere") == [JITA]


def test_freshness_tz_aware_recent_is_not_stale():
    recent = datetime.now(timezone.utc) - timedelta(seconds=1)
    iso, stale = tr._freshness(recent)
    assert stale is False
    assert iso == recent.isoformat()


def test_freshness_none_is_stale():
    iso, stale = tr._freshness(None)
    assert iso is None and stale is True


# --------------------------------------------------------------------------- #
# /portfolio (Markowitz allocation)
# --------------------------------------------------------------------------- #
def test_portfolio_allocates_budget_and_traces_frontier(db):
    from app.repositories import trade_repo
    trade_repo.upsert_trade_candidates(db, [
        _route(34, JITA, AMARR, margin_p=0.20, buy_price=100.0, daily_volume=10000.0),
        _route(36, AMARR, JITA, margin_p=0.40, buy_price=200.0, daily_volume=10000.0),
    ])
    out = call_portfolio(db, budget=1_000_000.0)
    res, t = out["result"], out["result"]["totals"]
    assert out["meta"]["n_considered"] == 2
    assert t["capital_used"] <= 1_000_000.0 + 1.0      # never overspends the budget
    assert t["n_assets"] >= 1 and t["expected_profit"] > 0
    assert res["frontier"] is not None and res["frontier"]["points"]
    a = res["allocations"][0]
    assert a["qty"] > 0 and "→" in a["best_method"]


def test_portfolio_keeps_best_route_per_item(db):
    from app.repositories import trade_repo
    trade_repo.upsert_trade_candidates(db, [
        _route(34, JITA, AMARR, margin_p=0.10, buy_price=100.0),   # profit 10
        _route(34, JITA, RENS, margin_p=0.30, buy_price=100.0),    # profit 30 ← best
    ])
    out = call_portfolio(db, budget=1_000_000.0)
    assert out["meta"]["n_considered"] == 1                        # deduped to one asset
    assert out["result"]["allocations"][0]["best_method"] == "Jita → Rens"


def test_portfolio_min_volume_filter_drops_illiquid(db):
    from app.repositories import trade_repo
    trade_repo.upsert_trade_candidates(db, [
        _route(34, JITA, AMARR, daily_volume=50.0),
        _route(36, AMARR, JITA, daily_volume=5000.0),
    ])
    out = call_portfolio(db, budget=1_000_000.0, min_volume=1000.0)
    assert {a["type_id"] for a in out["result"]["allocations"]} == {36}


def test_portfolio_empty_pool_is_safe(db):
    out = call_portfolio(db, budget=1_000_000.0)
    assert out["result"]["totals"]["n_assets"] == 0
    assert out["result"]["allocations"] == [] and out["result"]["frontier"] is None
