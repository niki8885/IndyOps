"""Smoke tests for trade_repo upserts/loaders against in-memory SQLite."""
from datetime import datetime

from app.core.database import TradeCandidate
from app.repositories import trade_repo

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


def test_distinct_candidate_type_ids(app_session):
    t = datetime(2026, 1, 1)
    trade_repo.upsert_trade_candidates(app_session, [
        _cand(0.1, t),
        {**_cand(0.1, t), "sell_hub": 60011866},   # same item, different route
        {**_cand(0.1, t), "item_id": 35},
    ])
    assert sorted(trade_repo.distinct_candidate_type_ids(app_session)) == [34, 35]
