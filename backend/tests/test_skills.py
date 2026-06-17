import pytest
from app.services import skills


def test_manufacturing_time_mult_stacks_industry_and_advanced():
    s = {skills.SKILL_INDUSTRY: 5, skills.SKILL_ADVANCED_INDUSTRY: 5}
    # (1 − 0.20) × (1 − 0.15) = 0.68
    assert skills.manufacturing_time_mult(s) == pytest.approx(0.68)


def test_reaction_time_mult_uses_advanced_industry_only():
    s = {skills.SKILL_INDUSTRY: 5, skills.SKILL_ADVANCED_INDUSTRY: 5}
    # Industry skill does NOT apply to reactions → only Advanced Industry's −15%.
    assert skills.reaction_time_mult(s) == pytest.approx(0.85)


def test_no_skills_means_no_reduction():
    assert skills.manufacturing_time_mult({}) == 1.0
    assert skills.reaction_time_mult({}) == 1.0


def test_sales_tax_drops_with_accounting():
    assert skills.sales_tax_pct({}) == pytest.approx(7.5)
    assert skills.sales_tax_pct({skills.SKILL_ACCOUNTING: 5}) == pytest.approx(7.5 * 0.45)


def test_broker_fee_drops_with_relations_and_standings_and_floors():
    assert skills.broker_fee_pct({}) == pytest.approx(3.0)
    # Broker Relations 5 → 3 − 1.5 = 1.5
    assert skills.broker_fee_pct({skills.SKILL_BROKER_RELATIONS: 5}) == pytest.approx(1.5)
    # standings shave more: 3 − 1.5 − 0.03×10 − 0.02×10 = 1.0 (hits the floor exactly)
    assert skills.broker_fee_pct({skills.SKILL_BROKER_RELATIONS: 5}, 10.0, 10.0) == pytest.approx(1.0)
    # negative standings give no benefit and the fee never drops below the floor
    assert skills.broker_fee_pct({skills.SKILL_BROKER_RELATIONS: 5}, -10.0, -10.0) == pytest.approx(1.5)


def test_reprocessing_skill_mult_stacks_three_skills():
    # (1+0.03×5)(1+0.02×5)(1+0.02×5) = 1.15 × 1.10 × 1.10
    assert skills.reprocessing_skill_mult(5, 5, 5) == pytest.approx(1.15 * 1.10 * 1.10)
    assert skills.reprocessing_skill_mult(0, 0, 0) == 1.0
    # ore-specific skill is optional and defaults to none
    assert skills.reprocessing_skill_mult(5, 5) == pytest.approx(1.15 * 1.10)


def test_reprocessing_yield_mult_reads_skill_map():
    s = {skills.SKILL_REPROCESSING: 5, skills.SKILL_REPROCESSING_EFFICIENCY: 4,
         skills.SKILL_ORE_PROCESSING["Veldspar"]: 3}
    expect = (1 + 0.03 * 5) * (1 + 0.02 * 4) * (1 + 0.02 * 3)
    got = skills.reprocessing_yield_mult(s, skills.SKILL_ORE_PROCESSING["Veldspar"])
    assert got == pytest.approx(expect)
    # without naming the ore skill, only the general skills apply
    assert skills.reprocessing_yield_mult(s) == pytest.approx((1 + 0.15) * (1 + 0.08))


def test_profile_bundles_everything():
    s = {skills.SKILL_INDUSTRY: 4, skills.SKILL_ADVANCED_INDUSTRY: 3,
         skills.SKILL_ACCOUNTING: 5, skills.SKILL_BROKER_RELATIONS: 4}
    p = skills.profile_from(123, "Pilot", s, best_faction_standing=5.0, best_corp_standing=2.5)
    assert p.character_id == 123 and p.character_name == "Pilot"
    assert p.man_time_mult == pytest.approx((1 - 0.16) * (1 - 0.09))
    assert p.react_time_mult == pytest.approx(1 - 0.09)
    assert p.sales_tax_pct == pytest.approx(round(7.5 * 0.45, 4))
    # 3 − 0.3×4 − 0.03×5 − 0.02×2.5 = 1.6
    assert p.broker_fee_pct == pytest.approx(1.6)
