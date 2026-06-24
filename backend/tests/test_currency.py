"""Bank currency conversion — Aureus / Penny (1 ISK = 1 Aureus, 0.01 ISK = 1 Penny)."""
from app.services import currency as cur


def test_isk_to_penny_is_exact_cents():
    assert cur.isk_to_penny(1000.11) == 100011
    assert cur.isk_to_penny(0.01) == 1
    assert cur.isk_to_penny(0) == 0
    assert cur.isk_to_penny(None) == 0


def test_example_from_spec():
    # 1,000.11 ISK = 1000 Aureus + 11 Penny
    coins = cur.isk_to_coins(1000.11)
    assert coins == {"total_penny": 100011, "aureus": 1000, "penny": 11}


def test_penny_split_and_carry():
    assert cur.penny_to_coins(250) == {"total_penny": 250, "aureus": 2, "penny": 50}
    assert cur.penny_to_coins(100) == {"total_penny": 100, "aureus": 1, "penny": 0}


def test_negative_balance_keeps_sign_on_both_parts():
    assert cur.penny_to_coins(-150) == {"total_penny": -150, "aureus": -1, "penny": -50}


def test_balance_sums_pennies_exactly():
    # floats would drift; integer Penny does not
    b = cur.balance([100011, 100011, 78])
    assert b["total_penny"] == 200100
    assert b == {"total_penny": 200100, "aureus": 2001, "penny": 0}
