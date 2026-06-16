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
