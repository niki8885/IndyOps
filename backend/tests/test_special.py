"""Special functions for the Student-t copula (shared algorithm with the engine)."""
import math

import numpy as np

from app.services import _special as sp
from app.services.profit_sim import norm_cdf


def test_norm_ppf_known_quantiles():
    assert math.isclose(float(sp.norm_ppf(0.975)), 1.959964, abs_tol=1e-5)
    assert math.isclose(float(sp.norm_ppf(0.5)), 0.0, abs_tol=1e-9)
    assert math.isclose(float(sp.norm_ppf(0.025)), -1.959964, abs_tol=1e-5)


def test_norm_ppf_inverts_norm_cdf():
    z = np.array([-2.5, -1.0, -0.2, 0.3, 1.4, 2.7])
    assert np.max(np.abs(sp.norm_ppf(norm_cdf(z)) - z)) < 1e-7


def test_norm_ppf_clamps_extremes():
    assert np.isfinite(sp.norm_ppf(0.0)) and np.isfinite(sp.norm_ppf(1.0))


def test_student_t_cdf_known_values():
    assert math.isclose(float(sp.student_t_cdf(0.0, 10)), 0.5, abs_tol=1e-9)
    # t_{0.95,10}=1.812461, t_{0.975,10}=2.228139
    assert math.isclose(float(sp.student_t_cdf(1.812461, 10)), 0.95, abs_tol=1e-4)
    assert math.isclose(float(sp.student_t_cdf(2.228139, 10)), 0.975, abs_tol=1e-4)
    assert math.isclose(float(sp.student_t_cdf(-2.228139, 10)), 0.025, abs_tol=1e-4)


def test_student_t_cdf_symmetry_and_limits():
    t = np.array([-3.0, -1.0, 0.0, 1.0, 3.0])
    c = sp.student_t_cdf(t, 7)
    assert np.allclose(c + c[::-1], 1.0, atol=1e-9)        # symmetric about 0
    assert np.all(np.diff(c) > 0)                          # monotone increasing


def test_student_t_cdf_approaches_normal_for_large_df():
    # ν → ∞ ⇒ Student-t → standard normal
    assert math.isclose(float(sp.student_t_cdf(1.959964, 1e6)), 0.975, abs_tol=1e-4)


def test_student_t_cdf_vectorized():
    out = sp.student_t_cdf(np.array([-1.0, 0.0, 1.0]), 5)
    assert out.shape == (3,) and math.isclose(out[1], 0.5, abs_tol=1e-9)
