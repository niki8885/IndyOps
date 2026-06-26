"""Unit tests for the realized trade-profit FIFO matcher (pure, no DB/network)."""
import datetime

from app.services import trade_profits


def _t(tid, is_buy, qty, price, day):
    return {"type_id": tid, "is_buy": is_buy, "quantity": qty, "unit_price": price,
            "date": datetime.datetime(2026, 6, day, 12, 0, 0)}


# ── match_trades ───────────────────────────────────────────────────────────────

def test_match_trades_single_with_fees():
    # buy 100 @ 5, sell 60 @ 8; broker 3%, tax 2%
    res = trade_profits.match_trades(
        [_t(34, True, 100, 5.0, 1), _t(34, False, 60, 8.0, 2)], broker_pct=3.0, tax_pct=2.0)
    assert res["unmatched"] == {}
    r = res["rows"][0]
    assert r["units"] == 60 and r["unit_buy"] == 5.0 and r["unit_sell"] == 8.0
    assert r["total_buy"] == 300.0 and r["total_sell"] == 480.0
    assert r["broker_buy"] == 9.0 and r["broker_sell"] == 14.4 and r["sales_tax"] == 9.6
    # 480 - 300 - 9 - 14.4 - 9.6 = 147
    assert r["profit"] == 147.0 and r["margin"] == 49.0


def test_match_trades_fifo_spans_lots():
    # 50 @ 4 then 50 @ 6; sell 80 @ 10 → consumes 50@4 + 30@6 = 380 cost
    res = trade_profits.match_trades(
        [_t(34, True, 50, 4.0, 1), _t(34, True, 50, 6.0, 2), _t(34, False, 80, 10.0, 3)],
        broker_pct=0.0, tax_pct=0.0)
    r = res["rows"][0]
    assert r["total_buy"] == 380.0 and r["unit_buy"] == 4.75
    assert r["total_sell"] == 800.0 and r["profit"] == 420.0
    assert res["unmatched"] == {}


def test_match_trades_unmatched_sell_has_no_cost_basis():
    res = trade_profits.match_trades([_t(34, False, 10, 5.0, 1)], broker_pct=0.0, tax_pct=0.0)
    assert res["rows"] == [] and res["unmatched"] == {34: 10}


def test_match_trades_partial_match_flags_remainder():
    # buy 30, sell 50 → 30 realized + 20 with no cost basis
    res = trade_profits.match_trades(
        [_t(34, True, 30, 5.0, 1), _t(34, False, 50, 9.0, 2)], broker_pct=0.0, tax_pct=0.0)
    assert res["rows"][0]["units"] == 30
    assert res["unmatched"] == {34: 20}


def test_match_trades_threads_sell_transaction_id():
    # the sell's transaction_id becomes sell_tx_id (the stable per-row exclude key)
    buy = {**_t(34, True, 10, 5.0, 1)}
    sell = {**_t(34, False, 10, 8.0, 2), "transaction_id": 987654321}
    res = trade_profits.match_trades([buy, sell])
    assert res["rows"][0]["sell_tx_id"] == 987654321


def test_match_trades_separates_items():
    res = trade_profits.match_trades(
        [_t(34, True, 10, 5.0, 1), _t(35, True, 10, 5.0, 1),
         _t(34, False, 10, 7.0, 2)], broker_pct=0.0, tax_pct=0.0)
    assert len(res["rows"]) == 1 and res["rows"][0]["type_id"] == 34
    assert res["unmatched"] == {}   # type 35 never sold → not unmatched, just held


def test_match_trades_pools_buy_and_sell_across_characters():
    # buy on the Jita alt, sell on another character — must still match (per-txn rates).
    buy = {**_t(34, True, 100, 5.0, 1), "character_id": 1, "character_name": "Zizo Jita",
           "broker_pct": 1.0, "tax_pct": 4.0}
    sell = {**_t(34, False, 100, 8.0, 2), "character_id": 2, "character_name": "Nikita",
            "broker_pct": 2.0, "tax_pct": 3.0}
    res = trade_profits.match_trades([buy, sell])
    assert res["unmatched"] == {}
    r = res["rows"][0]
    assert r["units"] == 100 and r["character_name"] == "Nikita"   # attributed to seller
    assert r["broker_buy"] == 5.0      # 500 buy value × 1% (buyer's rate)
    assert r["broker_sell"] == 16.0    # 800 sell value × 2% (seller's rate)
    assert r["sales_tax"] == 24.0      # 800 × 3% (seller's rate)
    assert r["profit"] == 255.0        # 800 − 500 − 5 − 16 − 24


# ── summarize_trades ─────────────────────────────────────────────────────────

def test_summarize_trades_totals_series_and_by_item():
    rows = [
        {"date": "2026-06-02", "type_id": 34, "name": "Tritanium", "units": 60,
         "total_buy": 300.0, "total_sell": 480.0, "broker_buy": 9.0, "broker_sell": 14.4,
         "sales_tax": 9.6, "profit": 147.0, "margin": 49.0},
        {"date": "2026-06-02", "type_id": 35, "name": "Pyerite", "units": 10,
         "total_buy": 100.0, "total_sell": 150.0, "broker_buy": 0.0, "broker_sell": 0.0,
         "sales_tax": 0.0, "profit": 50.0, "margin": 50.0},
    ]
    s = trade_profits.summarize_trades(rows)
    assert s["total_profit"] == 197.0
    assert s["total_buy"] == 400.0 and s["total_sell"] == 630.0
    assert s["total_broker"] == 23.4 and s["total_tax"] == 9.6
    assert s["trade_count"] == 2 and s["units"] == 70
    assert s["avg_margin"] == 49.25
    assert [x["date"] for x in s["series"]] == ["2026-06-02"]
    assert s["series"][0]["profit"] == 197.0
    assert s["by_item"][0]["type_id"] == 34    # higher profit first


def test_summarize_trades_win_loss_metrics():
    rows = [
        {"date": "2026-06-01", "type_id": 34, "name": "A", "units": 1, "total_buy": 100.0,
         "total_sell": 250.0, "broker_buy": 0.0, "broker_sell": 0.0, "sales_tax": 0.0,
         "profit": 150.0, "margin": 150.0},
        {"date": "2026-06-02", "type_id": 35, "name": "B", "units": 1, "total_buy": 100.0,
         "total_sell": 50.0, "broker_buy": 0.0, "broker_sell": 0.0, "sales_tax": 0.0,
         "profit": -50.0, "margin": -50.0},
    ]
    s = trade_profits.summarize_trades(rows)
    assert s["win_count"] == 1 and s["loss_count"] == 1
    assert s["win_rate"] == 50.0
    assert s["profit_factor"] == 3.0     # gross win 150 / gross loss 50
    assert s["avg_profit"] == 50.0       # (150 − 50) / 2 trades
    assert s["profit_per_day"] == 50.0   # 100 total / 2 distinct days


def test_summarize_trades_empty():
    s = trade_profits.summarize_trades([])
    assert s["total_profit"] == 0.0 and s["trade_count"] == 0
    assert s["avg_margin"] is None and s["series"] == [] and s["by_item"] == []
    assert s["win_count"] == 0 and s["win_rate"] is None and s["profit_factor"] is None
