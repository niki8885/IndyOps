"""
Scam-price guard goldens (IO-21). ``flag_unrealistic`` (basic calc) substitutes the
ESI adjusted price; ``resolve_price`` (chain) prefers another region or the sell side
before ever falling back to adjusted. Hand-computed thresholds, so a formula change
is caught.
"""
from app.services.pricing import flag_unrealistic, resolve_price


# ── flag_unrealistic (basic calculator) ────────────────────────────────────────

def test_flag_replaces_scam_with_adjusted():
    clean, flags = flag_unrealistic({34: 0.5}, {34: 5.0}, ratio=0.3)
    assert clean[34] == 5.0                       # 0.5 < 30% of 5.0 → use adjusted
    assert flags[34]["original"] == 0.5 and flags[34]["used"] == 5.0


def test_flag_keeps_price_above_threshold():
    clean, flags = flag_unrealistic({34: 2.0}, {34: 5.0}, ratio=0.3)
    assert clean[34] == 2.0 and flags == {}       # 2.0 ≥ 1.5 → kept


def test_flag_respects_skip_and_missing_adjusted():
    clean, flags = flag_unrealistic({34: 0.5, 35: 0.01}, {34: 5.0}, ratio=0.3, skip={34})
    assert clean[34] == 0.5                        # manual override → never touched
    assert clean[35] == 0.01 and flags == {}       # no adjusted for 35 → can't judge


def test_flag_ratio_zero_disables():
    clean, flags = flag_unrealistic({34: 0.01}, {34: 5.0}, ratio=0.0)
    assert clean[34] == 0.01 and flags == {}


# ── resolve_price (chain: region → sell → adjusted) ─────────────────────────────

def test_resolve_prefers_cheapest_realistic_region():
    # region 1 buy is a scam (0.5); region 2 buy (4.0) is realistic → use region 2.
    price, src, flag = resolve_price([(0.5, 1), (4.0, 2)], [(9.0, 1), (8.0, 2)],
                                     adjusted=5.0, ratio=0.3, basis="buy")
    assert price == 4.0 and src == 2 and flag is None


def test_resolve_falls_back_to_sell_when_all_buys_scam():
    price, src, flag = resolve_price([(0.5, 1), (0.4, 2)], [(8.0, 1), (7.0, 2)],
                                     adjusted=5.0, ratio=0.3, basis="buy")
    assert price == 7.0 and src == 2                       # cheapest realistic sell
    assert flag and flag["original"] == 0.4 and flag["used"] == 7.0


def test_resolve_falls_back_to_adjusted_last():
    price, src, flag = resolve_price([(0.5, 1)], [(0.6, 1)],
                                     adjusted=5.0, ratio=0.3, basis="buy")
    assert price == 5.0 and src == "adjusted" and flag["used"] == 5.0


def test_resolve_no_flag_when_data_merely_missing():
    # No buy data at all (not scammy) → use sell, but nothing was "ignored".
    price, src, flag = resolve_price([(None, 1)], [(8.0, 1)],
                                     adjusted=5.0, ratio=0.3, basis="buy")
    assert price == 8.0 and src == 1 and flag is None


def test_resolve_sell_basis_uses_sell_side_first():
    price, src, flag = resolve_price([(4.0, 1)], [(7.0, 1)],
                                     adjusted=5.0, ratio=0.3, basis="sell")
    assert price == 7.0 and src == 1 and flag is None
