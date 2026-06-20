"""Haul scanner: the worker discovers profitable Jita → C-J hauls from the liquid
Jita universe, and the repo round-trips/ranks them. Mocked ESI/SDE."""
from datetime import datetime

from sqlalchemy.orm import sessionmaker

from app.adapters import market
from app.core.database import HaulCandidate, TradeTypeStat
from app.repositories import eve_market, trade_repo
from app.tasks import update_trade


# ── repo ──────────────────────────────────────────────────────────────────────

def test_liquid_type_ids_filters_and_orders(app_session):
    forge = update_trade.JITA_REGION
    rows = [
        TradeTypeStat(region_id=forge, type_id=1, daily_volume=500.0, sample_days=14, computed_at=datetime(2026, 1, 1)),
        TradeTypeStat(region_id=forge, type_id=2, daily_volume=50.0, sample_days=14, computed_at=datetime(2026, 1, 1)),
        TradeTypeStat(region_id=forge, type_id=3, daily_volume=900.0, sample_days=14, computed_at=datetime(2026, 1, 1)),
        TradeTypeStat(region_id=999, type_id=4, daily_volume=999.0, sample_days=14, computed_at=datetime(2026, 1, 1)),
    ]
    app_session.add_all(rows)
    app_session.commit()
    out = trade_repo.liquid_type_ids(app_session, forge, min_volume=100, limit=10)
    assert out == [(3, 900.0), (1, 500.0)]            # vol≥100, desc, other region excluded


def test_replace_and_query_haul_candidates(app_session):
    trade_repo.replace_haul_candidates(app_session, [
        {"item_id": 10, "type_name": "A", "category_id": 7, "profit_per_unit": 100.0, "margin_pct": 0.20,
         "best_method": "sell_buy", "updated_at": datetime(2026, 1, 1)},
        {"item_id": 11, "type_name": "B", "category_id": 6, "profit_per_unit": 500.0, "margin_pct": 0.05,
         "best_method": "buy_sell", "updated_at": datetime(2026, 1, 1)},
    ])
    by_profit = trade_repo.query_haul_candidates(app_session, rank_by="profit")
    assert [r.item_id for r in by_profit] == [11, 10]          # 500 > 100
    by_roi = trade_repo.query_haul_candidates(app_session, rank_by="roi")
    assert [r.item_id for r in by_roi] == [10, 11]             # 0.20 > 0.05
    only_ships = trade_repo.query_haul_candidates(app_session, category_id=6)
    assert [r.item_id for r in only_ships] == [11]
    # replace is a full snapshot
    trade_repo.replace_haul_candidates(app_session, [])
    assert trade_repo.query_haul_candidates(app_session) == []


# ── worker ────────────────────────────────────────────────────────────────────

def test_run_haul_scan_keeps_profitable_drops_loss(app_engine, eve_engine, monkeypatch):
    AppSession = sessionmaker(bind=app_engine)
    monkeypatch.setattr(update_trade, "SessionLocal", AppSession)
    monkeypatch.setattr(update_trade, "EveSessionLocal", sessionmaker(bind=eve_engine))

    forge = update_trade.JITA_REGION
    s = AppSession()
    s.add_all([
        TradeTypeStat(region_id=forge, type_id=100, daily_volume=400.0, sample_days=14, computed_at=datetime(2026, 1, 1)),
        TradeTypeStat(region_id=forge, type_id=200, daily_volume=300.0, sample_days=14, computed_at=datetime(2026, 1, 1)),
        TradeTypeStat(region_id=forge, type_id=300, daily_volume=10.0, sample_days=14, computed_at=datetime(2026, 1, 1)),  # below floor
    ])
    s.commit(); s.close()

    monkeypatch.setattr(eve_market, "types_market_meta", lambda eve_db, ids: {
        100: {"type_name": "ProfitShip", "volume": 100.0, "market_group_id": 1, "published": True, "category_id": 6},
        200: {"type_name": "LossModule", "volume": 1.0, "market_group_id": 1, "published": True, "category_id": 7},
    })
    # Jita cheap / C-J rich for 100 (profit); reverse for 200 (loss).
    monkeypatch.setattr(market, "fuzzwork_aggregates_or_empty", lambda region, ids: {
        "100": {"buy": {"max": 1_000_000}, "sell": {"min": 1_100_000}},
        "200": {"buy": {"max": 5_000_000}, "sell": {"min": 5_200_000}},
    })
    monkeypatch.setattr(market, "gnf_local", lambda tid: {
        100: {"buy": 3_000_000, "sell": 3_200_000},
        200: {"buy": 1_000_000, "sell": 1_050_000},
    }.get(tid))

    summary = update_trade.run_haul_scan_update()
    assert summary["errors"] == []
    assert summary["universe"] == 2                 # only the two ≥100-vol types
    assert summary["candidates"] == 1               # only the profitable one kept

    s = AppSession()
    try:
        rows = s.query(HaulCandidate).all()
        assert [r.item_id for r in rows] == [100]
        assert rows[0].profit_per_unit > 0 and rows[0].best_method in update_trade.trade.HAUL_METHODS
    finally:
        s.close()
