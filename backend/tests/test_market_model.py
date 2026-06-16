"""Distribution & correlation estimation for the Monte-Carlo profit simulator."""
import math
import numpy as np
from app.services import market_model as mm


def test_lognormal_params_basic():
    mu, sigma = mm.lognormal_params([100, 110, 90, 105, 95])
    assert mu == np.log([100, 110, 90, 105, 95]).mean()
    assert sigma > 0


def test_lognormal_params_degenerate():
    assert mm.lognormal_params([]) == (0.0, 0.0)
    mu, sigma = mm.lognormal_params([50.0])     # single point → no spread
    assert sigma == 0.0 and math.isclose(mu, math.log(50.0))


def test_quantile_grid_shape_and_monotonic():
    grid = mm.quantile_grid([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert len(grid) == mm.QGRID_POINTS
    assert grid == sorted(grid)            # quantile function is non-decreasing
    assert grid[0] == 1.0 and grid[-1] == 10.0


def test_quantile_grid_empty_and_flat():
    assert mm.quantile_grid([]) == [0.0] * mm.QGRID_POINTS
    assert mm.quantile_grid([7.0, 7.0]) == [7.0] * mm.QGRID_POINTS


def test_relative_spread():
    s = mm.relative_spread([100, 100], [110, 110])    # mid 105, spread 10 → ~0.0952
    assert math.isclose(s, 10 / 105, rel_tol=1e-9)
    assert mm.relative_spread([], []) == 0.0


def test_correlation_matrix_identity_on_thin_data():
    # < 3 return rows → identity (independent)
    rets = mm.align_returns([[100, 101], [50, 51]])
    c = mm.correlation_matrix(rets, n=2)
    assert np.allclose(c, np.eye(2))


def test_cholesky_reproduces_target_correlation():
    target = np.array([[1.0, 0.8], [0.8, 1.0]])
    L = mm.nearest_psd_cholesky(target)
    rng = np.random.default_rng(0)
    z = rng.standard_normal((200_000, 2)) @ L.T
    emp = np.corrcoef(z, rowvar=False)[0, 1]
    assert abs(emp - 0.8) < 0.01


def test_cholesky_repairs_non_psd():
    # an invalid "correlation" (eigenvalues < 0) must not raise and stays unit-diag
    bad = np.array([[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]])
    L = mm.nearest_psd_cholesky(bad)
    assert L.shape == (3, 3)
    assert np.allclose(np.tril(L), L)            # lower-triangular
    reco = L @ L.T
    assert np.allclose(np.diag(reco), 1.0, atol=1e-6)


def test_factor_decompose_row_variance_is_unit():
    corr = np.array([[1.0, 0.6, 0.1], [0.6, 1.0, 0.1], [0.1, 0.1, 1.0]])
    loadings, fsig, idio = mm.factor_decompose(corr, [0, 0, 1])
    row_var = (loadings ** 2).sum(axis=1) + idio ** 2
    assert np.allclose(row_var, 1.0, atol=1e-9)
    assert loadings.shape == (3, 3)              # global + 2 groups
    assert np.allclose(fsig, 1.0)


def test_align_returns_tail_aligns_and_drops_nan():
    rets = mm.align_returns([[10, 20, 40, 80], [1, 2, 4, 8, 16]])  # diff lengths
    assert rets.shape == (3, 2)                  # min length 4 → 3 returns
    assert np.allclose(rets, np.log(2.0))        # both double each step


# ── IO-22 hardening: fat tails + price dynamics ─────────────────────────────────

def test_estimate_t_df_thin_vs_fat():
    rng = np.random.default_rng(0)
    normal = rng.standard_normal((600, 3))       # ~Gaussian → small excess kurtosis
    fat = rng.standard_t(4, size=(800, 3))       # heavy tails
    nu_normal = mm.estimate_t_df(normal)
    nu_fat = mm.estimate_t_df(fat)
    # MoM kurtosis is noisy near-Gaussian, but heavy tails give a clearly smaller ν
    assert nu_normal > nu_fat
    assert nu_normal >= 8.0 and 3.0 <= nu_fat <= 30.0


def test_fit_ar1_recovers_mean_reversion():
    # synthetic AR(1) in log space: x_t = c + rho·x_{t-1} + noise, rho=0.7
    rng = np.random.default_rng(2)
    rho, c = 0.7, 1.5
    x = [5.0]
    for _ in range(2000):
        x.append(c + rho * x[-1] + rng.normal(0, 0.05))
    phi, step_sigma, theta, x0 = mm.fit_ar1(list(np.exp(x)))
    assert abs((1.0 - phi) - rho) < 0.05          # phi = 1 - rho
    assert abs(theta - c / (1 - rho)) < 0.2        # long-run mean c/(1-rho)
    assert step_sigma > 0 and math.isclose(x0, x[-1], abs_tol=1e-9)


def test_fit_ar1_short_series_is_random_walk():
    phi, step_sigma, theta, x0 = mm.fit_ar1([100.0, 101.0])
    assert phi == 0.0                              # no reversion when too short


def test_garch_omega_variance_targets():
    # ω = σ²·(1−α−β) so unconditional variance = σ²
    omega = mm.garch_omega(0.2, 0.08, 0.90)
    assert math.isclose(omega, 0.2 ** 2 * (1 - 0.98), rel_tol=1e-9)
    assert mm.garch_omega(0.2, 0.5, 0.6) > 0       # clamps when α+β ≥ 1
