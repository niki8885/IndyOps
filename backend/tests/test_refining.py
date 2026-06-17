import pytest

from app.services.refining import (
    RefineSetup, RigYield, compute_yield, reprocess, effective_rig_bonus_pct,
)


def test_base_yield_only_no_skills_no_rigs():
    ry = compute_yield(RefineSetup(base_yield=0.50))
    assert ry.skill_mult == 1.0
    assert ry.rig_bonus_pct == 0.0
    assert ry.effective_yield == pytest.approx(0.50)


def test_full_setup_multiplies_all_factors():
    s = RefineSetup(base_yield=0.50, reprocessing_lvl=5, efficiency_lvl=5,
                    ore_specific_lvl=5, implant_pct=4,
                    rigs=(RigYield("T2 Reproc", 2.0),), security="null", tax_pct=5)
    ry = compute_yield(s)
    # 0.50 × 1.3915 × 1.04 × (1 + 4.2/100) × (1 − 0.05)
    expect = 0.50 * (1.15 * 1.10 * 1.10) * 1.04 * 1.042 * 0.95
    assert ry.gross_yield == pytest.approx(0.50 * 1.3915 * 1.04 * 1.042, rel=1e-4)
    assert ry.effective_yield == pytest.approx(expect, rel=1e-4)


def test_rig_security_modifier():
    rig = RigYield("rig", 2.0, hisec_mod=1.0, lowsec_mod=1.9, nullsec_mod=2.1)
    assert effective_rig_bonus_pct((rig,), "hi") == pytest.approx(2.0)
    assert effective_rig_bonus_pct((rig,), "low") == pytest.approx(3.8)
    assert effective_rig_bonus_pct((rig,), "null") == pytest.approx(4.2)


def test_rigs_stack_additively():
    rigs = (RigYield("a", 2.0), RigYield("b", 1.0))
    assert effective_rig_bonus_pct(rigs, "hi") == pytest.approx(3.0)


def test_effective_yield_clamped_to_one():
    # absurd base + rigs would exceed 100%; yield is capped at 1.0
    s = RefineSetup(base_yield=0.95, reprocessing_lvl=5, efficiency_lvl=5,
                    ore_specific_lvl=5, rigs=(RigYield("x", 50.0),), security="null")
    assert compute_yield(s).effective_yield == 1.0


def test_reprocess_floors_batches_and_minerals():
    ry = compute_yield(RefineSetup(base_yield=0.50))   # 0.50 flat
    # 250 units, portion 100 → 2 whole batches, 50 leftover
    res = reprocess(250, 100, [{"type_id": 34, "name": "Tritanium", "quantity": 415}],
                    ry, input_type_id=1230)
    assert res.batches == 2
    assert res.refined_units == 200
    assert res.leftover == 50
    m = res.minerals[0]
    assert m.perfect_qty == 2 * 415              # 830 at 100% yield
    assert m.qty == int(830 * 0.50)              # floored to 415


def test_reprocess_below_one_batch_yields_nothing():
    ry = compute_yield(RefineSetup(base_yield=0.50))
    res = reprocess(99, 100, [{"type_id": 34, "name": "Tritanium", "quantity": 415}], ry)
    assert res.batches == 0
    assert res.leftover == 99
    assert res.minerals[0].qty == 0
