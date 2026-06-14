"""Warehouse sell-allocation strategies — concrete cases."""
from app.services.allocation import Venue, allocate

VENUES = [
    Venue(1, "Jita", net_instant=90.0, net_patient=95.0, hist_vol=20.0),
    Venue(2, "Amarr", net_instant=88.0, net_patient=99.0, hist_vol=5.0),
]


def test_fast_dumps_into_best_instant():
    a = allocate(VENUES, 100, "fast", 7)
    assert len(a) == 1
    assert a[0].place_id == 1 and a[0].qty == 100        # 90 > 88
    assert a[0].method == "instant (buy order)"


def test_maxprofit_lists_best_patient():
    a = allocate(VENUES, 100, "maxprofit", 7)
    assert len(a) == 1
    assert a[0].place_id == 2 and a[0].method == "sell order"   # 99 > 95


def test_balanced_conserves_quantity():
    a = allocate(VENUES, 100, "balanced", 7)
    assert sum(x.qty for x in a) == 100


def test_balanced_fills_capacity_then_dumps_remainder_instant():
    # tiny daily volume → sell-order capacity (vol×days) can't absorb 100,
    # so the remainder falls through to the best instant venue.
    venues = [
        Venue(1, "Jita", net_instant=90.0, net_patient=95.0, hist_vol=1.0),
        Venue(2, "Amarr", net_instant=88.0, net_patient=99.0, hist_vol=1.0),
    ]
    a = allocate(venues, 100, "balanced", 2)        # cap = int(1×2) = 2 each
    assert sum(x.qty for x in a) == 100
    methods = {x.method for x in a}
    assert "sell order" in methods and "instant (buy order)" in methods
    instant = next(x for x in a if x.method == "instant (buy order)")
    assert instant.place_id == 1 and instant.qty == 96   # 100 − 2 − 2


def test_empty_without_a_priced_venue():
    assert allocate([Venue(1, "x", None, None, None)], 50, "fast", 7) == []
    assert allocate([], 50, "maxprofit", 7) == []
