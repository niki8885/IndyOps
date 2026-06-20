"""Jita → C-J haul evaluator: the pure 4-method margin math (services.trade.haul_eval)
and the router's paste parser."""
import pytest

from app.api import haul_router as hr
from app.services import trade


# ── pure margin math ──────────────────────────────────────────────────────────

def test_sell_buy_instant_both():
    # Buy from Jita sell (100, no fee), dump to C-J buy (150, −4.5% tax), no shipping.
    r = trade.haul_eval(jita_buy=90, jita_sell=100, cj_buy=150, cj_sell=160, qty=2,
                        acquire_side="sell", sell_side="buy", broker_fee=0.03, sales_tax=0.045)
    assert r["acquire_unit"] == pytest.approx(100.0)           # no broker on instant buy
    assert r["revenue_unit"] == pytest.approx(150 * 0.955)     # tax only
    assert r["unit_profit"] == pytest.approx(150 * 0.955 - 100)
    assert r["profit"] == pytest.approx((150 * 0.955 - 100) * 2)
    assert r["roi"] == pytest.approx(r["profit"] / r["capital"])


def test_buy_sell_patient_both_charges_broker_both_sides():
    # Place buy order @ Jita buy (90 +3% broker), list sell @ C-J sell (160 −3% −4.5%).
    r = trade.haul_eval(jita_buy=90, jita_sell=100, cj_buy=150, cj_sell=160, qty=1,
                        acquire_side="buy", sell_side="sell", broker_fee=0.03, sales_tax=0.045)
    assert r["acquire_unit"] == pytest.approx(90 * 1.03)
    assert r["revenue_unit"] == pytest.approx(160 * (1 - 0.03 - 0.045))


def test_shipping_reduces_profit_and_capital():
    base = trade.haul_eval(jita_buy=90, jita_sell=100, cj_buy=150, cj_sell=160, qty=1,
                          acquire_side="sell", sell_side="buy", broker_fee=0.03, sales_tax=0.045)
    ship = trade.haul_eval(jita_buy=90, jita_sell=100, cj_buy=150, cj_sell=160, qty=1,
                          acquire_side="sell", sell_side="buy", broker_fee=0.03, sales_tax=0.045,
                          shipping_per_unit=20)
    assert ship["unit_profit"] == pytest.approx(base["unit_profit"] - 20)
    assert ship["capital"] == pytest.approx(base["capital"] + 20)


def test_missing_price_returns_none():
    assert trade.haul_eval(jita_buy=None, jita_sell=None, cj_buy=150, cj_sell=160, qty=1,
                          acquire_side="sell", sell_side="buy", broker_fee=0.03, sales_tax=0.045) is None
    assert trade.haul_eval(jita_buy=90, jita_sell=100, cj_buy=0, cj_sell=None, qty=1,
                          acquire_side="buy", sell_side="buy", broker_fee=0.03, sales_tax=0.045) is None


def test_loss_making_item_has_negative_profit():
    # C-J pays less than Jita costs → loss.
    r = trade.haul_eval(jita_buy=900, jita_sell=1000, cj_buy=500, cj_sell=520, qty=1,
                        acquire_side="sell", sell_side="buy", broker_fee=0.03, sales_tax=0.045)
    assert r["profit"] < 0


# ── paste parser ──────────────────────────────────────────────────────────────

def test_parse_market_copy_format_takes_name_and_qty():
    text = "'Augmented' Mining Drone\t1\t15,300,000.00\t15,300,000.00\nAcolyte II\t3\t334,100.00\t1,002,300.00"
    out = dict(hr._parse_lines(text))
    assert out["'Augmented' Mining Drone"] == 1.0
    assert out["Acolyte II"] == 3.0


def test_parse_handles_x_qty_and_bare_name():
    out = dict(hr._parse_lines("Warrior II x5\nHobgoblin II"))
    assert out["Warrior II"] == 5.0
    assert out["Hobgoblin II"] == 1.0          # bare name defaults to qty 1


def test_parse_qty_first_tab_format():
    out = dict(hr._parse_lines("10\tNanite Repair Paste"))
    assert out["Nanite Repair Paste"] == 10.0


def test_method_table_covers_four_combos():
    assert set(hr.METHODS) == {"buy_sell", "buy_buy", "sell_sell", "sell_buy"}
    for acq, sell, _ in hr.METHODS.values():
        assert acq in ("buy", "sell") and sell in ("buy", "sell")


def test_best_haul_method_picks_highest_profit():
    # Wide spread → Buy→Sell (cheapest buy, highest sell) maximises profit.
    best = trade.best_haul_method(jita_buy=80, jita_sell=100, cj_buy=200, cj_sell=260, qty=1,
                                  broker_fee=0.03, sales_tax=0.045)
    assert best["method"] == "buy_sell"
    assert best["profit"] > 0


def test_best_haul_method_none_when_unpriceable():
    assert trade.best_haul_method(jita_buy=None, jita_sell=None, cj_buy=None, cj_sell=None,
                                  qty=1, broker_fee=0.03, sales_tax=0.045) is None
