"""Pure delivery-cost maths (services/delivery.py)."""
import math
import string

import pytest

from app.services import delivery as d


def test_light_years_zero_for_same_point():
    assert d.light_years(1, 2, 3, 1, 2, 3) == pytest.approx(0.0)


def test_light_years_one_ly():
    # exactly one light year along the x axis
    assert d.light_years(0, 0, 0, d.LY_METERS, 0, 0) == pytest.approx(1.0)


def test_light_years_euclidean():
    ly = d.light_years(0, 0, 0, d.LY_METERS, d.LY_METERS, d.LY_METERS)
    assert ly == pytest.approx(math.sqrt(3))


def test_trips_for_rounds_up():
    assert d.trips_for(0) == 0
    assert d.trips_for(1) == 1
    assert d.trips_for(d.JF_CARGO_M3) == 1
    assert d.trips_for(d.JF_CARGO_M3 + 1) == 2
    assert d.trips_for(700_001) == 3


def test_jf_cost_basic():
    # 1 trip, 5 ly × 100 iso/ly = 500 isotopes; × 10 ISK/iso = 5000 ISK
    r = d.jf_cost(100_000, ly=5.0, isotopes_per_ly=100.0, isotope_price=10.0)
    assert r["trips"] == 1
    assert r["total_isotopes"] == pytest.approx(500.0)
    assert r["total_cost"] == pytest.approx(5_000.0)
    assert r["cost_per_m3"] == pytest.approx(0.05)


def test_jf_cost_round_trip_doubles_isotopes():
    one = d.jf_cost(100_000, 5.0, 100.0, 10.0, round_trip=False)
    two = d.jf_cost(100_000, 5.0, 100.0, 10.0, round_trip=True)
    assert two["total_isotopes"] == 2 * one["total_isotopes"]
    assert two["total_cost"] == 2 * one["total_cost"]


def test_jf_cost_multiple_trips():
    # 800k m³ → 3 trips (ceil 800k/350k)
    r = d.jf_cost(800_000, ly=2.0, isotopes_per_ly=100.0, isotope_price=1.0)
    assert r["trips"] == 3
    assert r["total_isotopes"] == pytest.approx(3 * 2.0 * 100.0)


def test_jf_cost_zero_volume_is_safe():
    r = d.jf_cost(0, 5.0, 100.0, 10.0)
    assert r["trips"] == 0
    assert r["total_cost"] == pytest.approx(0.0)
    assert r["cost_per_m3"] == pytest.approx(0.0)


def test_regular_cost():
    r = d.regular_cost(total_volume=10_000, jumps=8, isk_per_jump_m3=2.0)
    assert r["total_cost"] == pytest.approx(8 * 2.0 * 10_000)
    assert r["cost_per_m3"] == pytest.approx(16.0)


def test_regular_cost_zero_volume_is_safe():
    r = d.regular_cost(0, 8, 2.0)
    assert r["total_cost"] == pytest.approx(0.0)
    assert r["cost_per_m3"] == pytest.approx(0.0)


def test_gen_code_length_and_charset():
    code = d.gen_code()
    assert len(code) == 10
    allowed = set(string.ascii_uppercase + string.digits)
    assert set(code) <= allowed


def test_gen_code_custom_length():
    assert len(d.gen_code(6)) == 6


def test_gen_code_is_random():
    # vanishingly unlikely to collide
    assert d.gen_code() != d.gen_code()


def test_jf_isotope_map_has_four_ships():
    assert set(d.JF_ISOTOPES) == {"Ark", "Rhea", "Nomad", "Anshar"}
    assert d.JF_ISOTOPES["Ark"] == "Helium Isotopes"


def test_build_comment_pipe_format():
    c = d.build_comment("Helium Run", "2026-06-17", "ABC123XY90", "Jita",
                        collateral=1_200_000_000, cost=0)
    assert "Helium Run" in c
    assert "2026-06-17" in c
    assert "ABC123XY90" in c
    assert "→ Jita" in c
    assert "1.20B ISK" in c
    assert "cost 0 ISK" in c
    assert c.count("|") == 5


def test_build_comment_defaults_project_label():
    c = d.build_comment(None, "2026-06-17", "CODE000000", None, 0, 0)
    assert c.startswith("Delivery |")
    assert "→" not in c  # no target segment
