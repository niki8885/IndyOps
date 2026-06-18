"""Concentration / liquidity index math."""
import math

import pytest

from app.services.indices import concentration, liquidity


@pytest.mark.parametrize("n", [1, 2, 3, 5, 8, 13, 50])
def test_uniform_basket_entropy_is_log_n(n):
    # Shannon entropy of N equal weights is exactly log N.
    c = concentration([7.0] * n)        # any positive constant; weights normalise
    assert abs(c.entropy - math.log(n)) < 1e-6
    assert abs(c.h_index - 1 / n) < 1e-6           # Herfindahl of uniform == 1/N
    assert abs(c.top3_share - min(3, n) / n) < 1e-6


def test_single_dominant_basket():
    c = concentration([100.0, 0.0, 0.0])
    assert c.top3_share == pytest.approx(1.0)
    assert c.h_index == pytest.approx(1.0)
    assert c.entropy == pytest.approx(0.0)


def test_concentration_ignores_nonpositive_weights():
    assert concentration([5.0, 0.0, -3.0]) == concentration([5.0])


def test_liquidity_needs_two_points():
    assert liquidity([]) is None
    assert liquidity([10.0]) is None


def test_liquidity_zero_variance_is_none():
    assert liquidity([10.0, 10.0, 10.0]) is None


def test_liquidity_value():
    # mean 2, population std sqrt(2/3) → 2 / 0.8165 ≈ 2.4495
    assert liquidity([1.0, 2.0, 3.0]) == pytest.approx(2.4495)
