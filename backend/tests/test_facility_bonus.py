import pytest
from app.services.facility_bonus import (
    RigBonus, effective_bonuses, rig_applies, _CAT_SHIP,
)

BASIC = "Standup M-Set Basic Medium Ship Manufacturing Material Efficiency"
ADV = "Standup M-Set Advanced Medium Ship Manufacturing Material Efficiency"
UNTIERED = "Standup L-Set Ship Manufacturing Efficiency"


def test_basic_rig_only_applies_to_tech1():
    # T1 medium ship (no meta row → treated as Tech I)
    assert rig_applies(BASIC, _CAT_SHIP, "Cruiser", meta_group_id=None) is True
    assert rig_applies(BASIC, _CAT_SHIP, "Cruiser", meta_group_id=1) is True
    # T2 medium ship (Basilisk) — basic must NOT apply
    assert rig_applies(BASIC, _CAT_SHIP, "Logistics Cruiser", meta_group_id=2) is False


def test_advanced_rig_only_applies_to_tech2():
    assert rig_applies(ADV, _CAT_SHIP, "Logistics Cruiser", meta_group_id=2) is True
    assert rig_applies(ADV, _CAT_SHIP, "Strategic Cruiser", meta_group_id=14) is True
    # T1 cruiser — advanced must NOT apply
    assert rig_applies(ADV, _CAT_SHIP, "Cruiser", meta_group_id=None) is False


def test_untiered_rig_applies_regardless_of_tech():
    assert rig_applies(UNTIERED, _CAT_SHIP, "Cruiser", meta_group_id=None) is True
    assert rig_applies(UNTIERED, _CAT_SHIP, "Logistics Cruiser", meta_group_id=2) is True


def test_basilisk_counts_only_the_advanced_rig():
    """The reported bug: a facility with both Basic + Advanced Medium rigs double-
    discounted a T2 cruiser. Now only the Advanced rig contributes."""
    rigs = [
        RigBonus(1, BASIC, me_bonus=-2.0, nullsec_mod=2.1),
        RigBonus(2, ADV, me_bonus=-2.4, nullsec_mod=2.1),
    ]
    eff = effective_bonuses(rigs, "null", _CAT_SHIP, "Logistics Cruiser", meta_group_id=2)
    assert eff.me_pct == pytest.approx(2.4 * 2.1)        # advanced only, not 2.0+2.4 stacked
    applied = {r["name"]: r["applies"] for r in eff.rigs}
    assert applied[ADV] is True
    assert applied[BASIC] is False


def test_t1_cruiser_counts_only_the_basic_rig():
    rigs = [
        RigBonus(1, BASIC, me_bonus=-2.0, nullsec_mod=2.1),
        RigBonus(2, ADV, me_bonus=-2.4, nullsec_mod=2.1),
    ]
    eff = effective_bonuses(rigs, "null", _CAT_SHIP, "Cruiser", meta_group_id=None)
    assert eff.me_pct == pytest.approx(2.0 * 2.1)        # basic only


LARGE = "Standup L-Set Basic Large Ship Manufacturing Material Efficiency"
CAPITAL = "Standup L-Set Capital Ship Manufacturing Efficiency"


def test_large_rig_applies_to_battleship_not_capital():
    """The reported bug: a Raven (Battleship) was matched by a Capital rig. A Large
    Ship rig must cover battleship-class hulls and a Capital rig must not."""
    assert rig_applies(LARGE, _CAT_SHIP, "Battleship", meta_group_id=None) is True
    assert rig_applies(LARGE, _CAT_SHIP, "Dreadnought", meta_group_id=None) is False


def test_capital_rig_applies_to_capitals_not_battleship():
    assert rig_applies(CAPITAL, _CAT_SHIP, "Dreadnought", meta_group_id=None) is True
    assert rig_applies(CAPITAL, _CAT_SHIP, "Carrier", meta_group_id=None) is True
    assert rig_applies(CAPITAL, _CAT_SHIP, "Capital Industrial Ship", meta_group_id=None) is True
    # Raven is a Battleship — the Capital rig must NOT apply (the original bug).
    assert rig_applies(CAPITAL, _CAT_SHIP, "Battleship", meta_group_id=None) is False
