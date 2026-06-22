"""Haul scanner: the worker discovers profitable Jita → C-J hauls from the liquid
Jita universe, and the repo round-trips/ranks them. Mocked ESI/SDE."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy.orm import sessionmaker

from app.adapters import market
from app.api import haul_router
from app.core.database import HaulCandidate, TradeTypeStat
from app.repositories import eve_market, trade_repo
from app.tasks import update_trade

USER = SimpleNamespace(id=1)


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


def test_query_filters_by_group_meta_and_type_ids(app_session):
    trade_repo.replace_haul_candidates(app_session, [
        {"item_id": 1, "type_name": "T1mod", "category_id": 7, "group_id": 60, "meta_group_id": None,
         "profit_per_unit": 100.0, "margin_pct": 0.10, "best_method": "sell_buy", "updated_at": datetime(2026, 1, 1)},
        {"item_id": 2, "type_name": "T2mod", "category_id": 7, "group_id": 60, "meta_group_id": 2,
         "profit_per_unit": 100.0, "margin_pct": 0.10, "best_method": "sell_buy", "updated_at": datetime(2026, 1, 1)},
        {"item_id": 3, "type_name": "FactionMod", "category_id": 7, "group_id": 60, "meta_group_id": 4,
         "profit_per_unit": 100.0, "margin_pct": 0.10, "best_method": "sell_buy", "updated_at": datetime(2026, 1, 1)},
        {"item_id": 4, "type_name": "Booster", "category_id": 20, "group_id": 303, "meta_group_id": None,
         "profit_per_unit": 100.0, "margin_pct": 0.10, "best_method": "sell_buy", "updated_at": datetime(2026, 1, 1)},
    ])
    # meta filter: T2 + Faction excludes the NULL(=T1) module, keeps T2/Faction/booster(NULL→T1?)…
    t2_faction = {r.item_id for r in trade_repo.query_haul_candidates(app_session, meta_groups={2, 4})}
    assert t2_faction == {2, 3}                       # NULL meta (1,4-as-booster) excluded
    # T1 includes NULL meta rows
    t1 = {r.item_id for r in trade_repo.query_haul_candidates(app_session, meta_groups={1})}
    assert t1 == {1, 4}
    # group filter (Drugs) overrides category
    drugs = [r.item_id for r in trade_repo.query_haul_candidates(app_session, group_ids=[303])]
    assert drugs == [4]
    # explicit type_ids restriction
    subset = {r.item_id for r in trade_repo.query_haul_candidates(app_session, type_ids=[2, 4])}
    assert subset == {2, 4}


# ── endpoint / serialisation ────────────────────────────────────────────────

def test_scan_row_includes_jita_buy_volume():
    r = HaulCandidate(item_id=7, type_name="Widget", jita_buy=1.0, jita_sell=2.0,
                      cj_buy=3.0, cj_sell=4.0, daily_volume=500.0, jita_buy_volume=1234.0,
                      best_method="sell_buy", profit_per_unit=10.0, margin_pct=0.2)
    row = haul_router._scan_row(r)
    assert row["jita_buy_volume"] == 1234.0
    assert row["daily_volume"] == 500.0


def test_haul_scan_endpoint_exposes_fees_for_client_repricing(app_session):
    from app.core import config
    trade_repo.replace_haul_candidates(app_session, [
        {"item_id": 10, "type_name": "A", "category_id": 7, "jita_buy_volume": 900.0,
         "profit_per_unit": 100.0, "margin_pct": 0.20, "best_method": "sell_buy",
         "updated_at": datetime(2026, 1, 1)},
    ])
    # Route declares its params with FastAPI Query(...) sentinels — pass the real
    # defaults explicitly since there's no HTTP layer to resolve them.
    res = asyncio.run(haul_router.haul_scan(
        min_margin=0.0, method=None, category_id=None, group=None, meta=None,
        rank_by="profit", limit=100, current_user=USER, db=app_session))
    assert res["broker_fee"] == config.TRADE_BROKER_FEE
    assert res["sales_tax"] == config.TRADE_SALES_TAX
    assert res["items"][0]["jita_buy_volume"] == 900.0


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


def test_run_haul_scan_records_jita_buy_volume(app_engine, eve_engine, monkeypatch):
    """The scanner stores the Jita buy-order depth (aggregate buy 'volume') so the UI
    can offer the anti-stagnation filter."""
    AppSession = sessionmaker(bind=app_engine)
    monkeypatch.setattr(update_trade, "SessionLocal", AppSession)
    monkeypatch.setattr(update_trade, "EveSessionLocal", sessionmaker(bind=eve_engine))

    forge = update_trade.JITA_REGION
    s = AppSession()
    s.add(TradeTypeStat(region_id=forge, type_id=100, daily_volume=400.0, sample_days=14,
                        computed_at=datetime(2026, 1, 1)))
    s.commit(); s.close()

    monkeypatch.setattr(eve_market, "types_market_meta", lambda eve_db, ids: {
        100: {"type_name": "ProfitShip", "volume": 100.0, "market_group_id": 1, "published": True, "category_id": 6},
    })
    monkeypatch.setattr(market, "fuzzwork_aggregates_or_empty", lambda region, ids: {
        "100": {"buy": {"max": 1_000_000, "volume": 4242}, "sell": {"min": 1_100_000}},
    })
    monkeypatch.setattr(market, "gnf_local", lambda tid: {"buy": 3_000_000, "sell": 3_200_000})

    assert update_trade.run_haul_scan_update()["candidates"] == 1
    s = AppSession()
    try:
        row = s.query(HaulCandidate).filter_by(item_id=100).one()
        assert row.jita_buy_volume == 4242.0
    finally:
        s.close()


def test_run_haul_scan_excludes_fighters_includes_drugs(app_engine, eve_engine, monkeypatch):
    AppSession = sessionmaker(bind=app_engine)
    monkeypatch.setattr(update_trade, "SessionLocal", AppSession)
    monkeypatch.setattr(update_trade, "EveSessionLocal", sessionmaker(bind=eve_engine))

    forge = update_trade.JITA_REGION
    s = AppSession()
    s.add_all([
        TradeTypeStat(region_id=forge, type_id=100, daily_volume=400.0, sample_days=14, computed_at=datetime(2026, 1, 1)),
        TradeTypeStat(region_id=forge, type_id=200, daily_volume=300.0, sample_days=14, computed_at=datetime(2026, 1, 1)),
        TradeTypeStat(region_id=forge, type_id=300, daily_volume=200.0, sample_days=14, computed_at=datetime(2026, 1, 1)),
    ])
    s.commit(); s.close()

    # 100 ship (kept), 200 fighter cat 87 (dropped), 300 booster group 303 / cat 20 (kept by group)
    monkeypatch.setattr(eve_market, "types_market_meta", lambda eve_db, ids: {
        100: {"type_name": "Ship", "volume": 100.0, "market_group_id": 1, "published": True,
              "category_id": 6, "group_id": 25, "meta_group_id": 1},
        200: {"type_name": "Fighter", "volume": 100.0, "market_group_id": 1, "published": True,
              "category_id": 87, "group_id": 1537, "meta_group_id": 2},
        300: {"type_name": "Booster", "volume": 1.0, "market_group_id": 1, "published": True,
              "category_id": 20, "group_id": 303, "meta_group_id": None},
    })
    # all three priced profitably (Jita cheap, C-J rich)
    monkeypatch.setattr(market, "fuzzwork_aggregates_or_empty", lambda region, ids: {
        "100": {"buy": {"max": 1_000_000}, "sell": {"min": 1_100_000}},
        "200": {"buy": {"max": 1_000_000}, "sell": {"min": 1_100_000}},
        "300": {"buy": {"max": 1_000_000}, "sell": {"min": 1_100_000}},
    })
    monkeypatch.setattr(market, "gnf_local", lambda tid: {"buy": 3_000_000, "sell": 3_200_000})

    summary = update_trade.run_haul_scan_update()
    assert summary["errors"] == []

    s = AppSession()
    try:
        rows = {r.item_id: r for r in s.query(HaulCandidate).all()}
        assert set(rows) == {100, 300}                 # fighter (200) excluded; booster (300) kept
        assert rows[300].group_id == 303 and rows[300].category_id == 20
        assert rows[100].meta_group_id == 1
    finally:
        s.close()
