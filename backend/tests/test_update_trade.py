"""End-to-end test of the fast trade-orders collector with mocked ESI + SDE.

Exercises the order-book reduction, universe selection, the three filters, and
the directional cross-hub logic — verifying a profitable route survives while
the unprofitable reverse direction is dropped.
"""
from datetime import datetime

from sqlalchemy.orm import sessionmaker

from app.adapters import market
from app.core.database import TradeCandidate, StationTradeCandidate, TradeTypeStat
from app.core.trade_data import HUBS
from app.repositories import eve_market
from app.tasks import update_trade


def _order(type_id, price, is_buy, station_id, vol=100000):
    return {"type_id": type_id, "price": price, "is_buy_order": is_buy,
            "location_id": station_id, "volume_remain": vol}


def test_run_trade_orders_end_to_end(app_engine, eve_engine, monkeypatch):
    AppSession = sessionmaker(bind=app_engine)
    monkeypatch.setattr(update_trade, "SessionLocal", AppSession)
    monkeypatch.setattr(update_trade, "EveSessionLocal", sessionmaker(bind=eve_engine))

    jita, amarr = HUBS["Jita"], HUBS["Amarr"]

    def fake_books(region_id, max_pages=300):
        if region_id == jita["region_id"]:
            return [_order(34, 1_000_000, False, jita["station_id"]),   # best sell
                    _order(34, 800_000, True, jita["station_id"])]       # best buy (wide spread)
        if region_id == amarr["region_id"]:
            return [_order(34, 1_200_000, False, amarr["station_id"]),
                    _order(34, 1_150_000, True, amarr["station_id"])]
        return []

    monkeypatch.setattr(market, "esi_region_orders_all", fake_books)
    monkeypatch.setattr(eve_market, "types_market_meta", lambda eve_db, ids: {
        34: {"type_name": "WidgetModule", "volume": 0.01, "market_group_id": 1, "published": True, "category_id": 7},
    })

    # history-derived liquidity/volatility present for both hub regions (passes filters)
    s = AppSession()
    for region in (jita["region_id"], amarr["region_id"]):
        s.add(TradeTypeStat(region_id=region, type_id=34, daily_volume=1_000_000.0,
                            volatility_cv=0.05, sample_days=14, computed_at=datetime(2026, 1, 1)))
    s.commit()
    s.close()

    summary = update_trade.run_trade_orders_update()
    assert summary["errors"] == []
    assert summary["universe"] == 1

    s = AppSession()
    try:
        rows = s.query(TradeCandidate).all()
        routes = {(r.buy_hub, r.sell_hub): r for r in rows}
        # profitable direction Jita → Amarr survives with positive margin + a volume score
        win = routes.get((jita["station_id"], amarr["station_id"]))
        assert win is not None and win.margin_pct_patient > 0
        assert win.margin_pct_instant is not None and 0.0 <= win.volume_score <= 1.0
        # unprofitable reverse Amarr → Jita is filtered out
        assert (amarr["station_id"], jita["station_id"]) not in routes
        # the wide-spread in-station flip at Jita survives; the thin Amarr one does not
        stations = {r.hub for r in s.query(StationTradeCandidate).all()}
        assert jita["station_id"] in stations
        assert amarr["station_id"] not in stations
    finally:
        s.close()
