"""Smoke tests for trade_repo upserts/loaders against in-memory SQLite."""
from datetime import datetime

from app.core.database import TradeCandidate, StationTradeCandidate
from app.core.trade_data import HUB_STATION_IDS
from app.repositories import trade_repo

JITA, AMARR, RENS = HUB_STATION_IDS["Jita"], HUB_STATION_IDS["Amarr"], HUB_STATION_IDS["Rens"]

# the model's DateTime column is naive (matches the rest of the schema); use
# naive timestamps here so round-tripped values compare equal under SQLite.


def _cand(margin, ts):
    return {
        "item_id": 34, "buy_hub": 60003760, "sell_hub": 60008494,
        "type_name": "Tritanium", "buy_price": 5.0, "sell_price_patient": 7.0,
        "margin_pct_patient": margin, "daily_volume": 1000.0, "volatility_cv": 0.05,
        "volume_score": 0.5, "updated_at": ts,
    }


def test_upsert_trade_candidates_is_idempotent(app_session):
    t1 = datetime(2026, 1, 1)
    assert trade_repo.upsert_trade_candidates(app_session, [_cand(0.1, t1)]) == 1
    assert app_session.query(TradeCandidate).count() == 1

    # same PK, new margin + timestamp → updates in place, not a second row
    t2 = datetime(2026, 1, 2)
    trade_repo.upsert_trade_candidates(app_session, [_cand(0.25, t2)])
    rows = app_session.query(TradeCandidate).all()
    assert len(rows) == 1
    assert rows[0].margin_pct_patient == 0.25
    assert rows[0].updated_at == t2


def test_upsert_empty_is_noop(app_session):
    assert trade_repo.upsert_trade_candidates(app_session, []) == 0
    assert app_session.query(TradeCandidate).count() == 0


def test_type_stats_roundtrip_and_load(app_session):
    now = datetime(2026, 1, 1)
    rows = [
        {"region_id": 10000002, "type_id": 34, "daily_volume": 5e8,
         "volatility_cv": 0.04, "sample_days": 14, "computed_at": now},
        {"region_id": 10000043, "type_id": 34, "daily_volume": 1e8,
         "volatility_cv": 0.06, "sample_days": 14, "computed_at": now},
    ]
    assert trade_repo.upsert_type_stats(app_session, rows) == 2

    forge = trade_repo.load_type_stats(app_session, 10000002, [34, 35])
    assert set(forge) == {34}
    assert forge[34]["daily_volume"] == 5e8
    assert trade_repo.load_type_stats(app_session, 10000002, []) == {}


def _route(item_id, buy_hub, sell_hub, margin, score, buy_price=100.0):
    return {
        "item_id": item_id, "buy_hub": buy_hub, "sell_hub": sell_hub,
        "type_name": f"Item{item_id}", "buy_price": buy_price,
        "sell_price_patient": buy_price * (1 + margin), "margin_pct_patient": margin,
        "item_volume_m3": 1.0, "daily_volume": 1000.0, "volatility_cv": 0.05,
        "volume_score": score, "updated_at": datetime(2026, 1, 1),
    }


def test_query_candidates_ranks_by_margin_times_score(app_session):
    trade_repo.upsert_trade_candidates(app_session, [
        _route(34, JITA, AMARR, 0.20, 0.5),   # score 0.10
        _route(35, JITA, RENS, 0.10, 1.0),    # score 0.10
        _route(36, AMARR, JITA, 0.50, 0.9),   # score 0.45  ← best
        _route(37, JITA, AMARR, 0.01, 0.1),   # score 0.001 ← worst
    ])
    ranked = trade_repo.query_candidates(app_session, limit=10)
    assert ranked[0].item_id == 36
    assert ranked[-1].item_id == 37


def test_query_candidates_filters(app_session):
    trade_repo.upsert_trade_candidates(app_session, [
        _route(34, JITA, AMARR, 0.20, 0.5, buy_price=100.0),
        _route(36, AMARR, JITA, 0.50, 0.9, buy_price=5_000.0),
    ])
    # restrict to buying from Jita → drops the Amarr-sourced route
    only_jita = trade_repo.query_candidates(app_session, buy_stations=[JITA])
    assert [r.item_id for r in only_jita] == [34]
    # budget excludes the expensive 5,000-ISK item
    affordable = trade_repo.query_candidates(app_session, max_buy_price=1_000.0)
    assert [r.item_id for r in affordable] == [34]
    # margin floor keeps only the high-margin route
    rich = trade_repo.query_candidates(app_session, min_margin=0.3)
    assert [r.item_id for r in rich] == [36]


def test_query_station_candidates_and_latest_updated_at(app_session):
    trade_repo.upsert_station_candidates(app_session, [
        {"item_id": 34, "hub": JITA, "type_name": "A", "buy_price": 90.0, "sell_price": 100.0,
         "margin_pct": 0.05, "profit_isk": 5.0, "daily_volume": 1000.0, "volatility_cv": 0.05,
         "volume_score": 0.4, "updated_at": datetime(2026, 1, 3)},
        {"item_id": 35, "hub": AMARR, "type_name": "B", "buy_price": 90.0, "sell_price": 120.0,
         "margin_pct": 0.30, "profit_isk": 25.0, "daily_volume": 1000.0, "volatility_cv": 0.05,
         "volume_score": 0.9, "updated_at": datetime(2026, 1, 3)},
    ])
    ranked = trade_repo.query_station_candidates(app_session)
    assert ranked[0].item_id == 35     # 0.30·0.9 > 0.05·0.4
    jita_only = trade_repo.query_station_candidates(app_session, stations=[JITA])
    assert [r.item_id for r in jita_only] == [34]
    assert trade_repo.latest_updated_at(app_session, StationTradeCandidate) == datetime(2026, 1, 3)


def test_distinct_candidate_type_ids(app_session):
    t = datetime(2026, 1, 1)
    trade_repo.upsert_trade_candidates(app_session, [
        _cand(0.1, t),
        {**_cand(0.1, t), "sell_hub": 60011866},   # same item, different route
        {**_cand(0.1, t), "item_id": 35},
    ])
    assert sorted(trade_repo.distinct_candidate_type_ids(app_session)) == [34, 35]
