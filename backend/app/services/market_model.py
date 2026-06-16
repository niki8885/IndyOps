from __future__ import annotations
import math

import numpy as np

QGRID_POINTS = 101  # quantile-function resolution


# marginals

def _clean_positive(hist) -> np.ndarray:
    """Finite, strictly-positive samples as a float array (prices are > 0)."""
    a = np.asarray(list(hist), dtype=float)
    return a[np.isfinite(a) & (a > 0.0)]


def lognormal_params(hist) -> tuple[float, float]:
    """``(mu, sigma)`` of ``log(price)`` — sample std (ddof=1). ``sigma=0`` when
    there are fewer than two usable points (degenerate → deterministic price)."""
    a = _clean_positive(hist)
    if a.size == 0:
        return 0.0, 0.0
    lg = np.log(a)
    mu = float(lg.mean())
    sigma = float(lg.std(ddof=1)) if a.size >= 2 else 0.0
    return mu, sigma


def quantile_grid(hist, k: int = QGRID_POINTS) -> list[float]:
    """``k``-point empirical quantile function (numpy linear-interp percentiles
    over 0…100). A flat grid at the single value when history is degenerate; all
    zeros when empty. Sampling: ``price = grid[ u·(k-1) ]`` with linear interp."""
    a = _clean_positive(hist)
    if a.size == 0:
        return [0.0] * k
    qs = np.linspace(0.0, 100.0, k)
    return [float(x) for x in np.percentile(a, qs)]


def relative_spread(buy_hist, sell_hist) -> float:
    """Mean relative bid/ask spread ``(sell - buy) / mid`` from aligned history.
    ``0`` when it can't be computed. Clamped to ``[0, 1]``."""
    b = np.asarray(list(buy_hist), dtype=float)
    s = np.asarray(list(sell_hist), dtype=float)
    n = min(b.size, s.size)
    if n == 0:
        return 0.0
    b, s = b[-n:], s[-n:]
    mid = (b + s) / 2.0
    ok = np.isfinite(b) & np.isfinite(s) & (mid > 0.0) & (s >= b)
    if not ok.any():
        return 0.0
    return float(np.clip(((s[ok] - b[ok]) / mid[ok]).mean(), 0.0, 1.0))


# cross-variable dependency

def align_returns(price_columns: list[list[float]]) -> np.ndarray:
    """Tail-align equal-purpose price series to the shortest length and return the
    matrix of log-returns."""
    cols = [np.asarray(c, dtype=float) for c in price_columns]
    if not cols:
        return np.empty((0, 0))
    t = min(c.size for c in cols)
    if t < 2:
        return np.empty((0, len(cols)))
    mat = np.column_stack([c[-t:] for c in cols])
    with np.errstate(divide="ignore", invalid="ignore"):
        rets = np.diff(np.log(mat), axis=0)
    good = np.isfinite(rets).all(axis=1)
    return rets[good]


def correlation_matrix(returns: np.ndarray, n: int | None = None) -> np.ndarray:
    """Pearson correlation of the columns of ``returns``"""
    if returns.ndim != 2 or returns.shape[0] < 3:
        return np.eye(returns.shape[1] if returns.size else (n or 0))
    with np.errstate(divide="ignore", invalid="ignore"):
        c = np.corrcoef(returns, rowvar=False)
    c = np.atleast_2d(c)
    c[~np.isfinite(c)] = 0.0
    np.fill_diagonal(c, 1.0)
    return c


def nearest_psd_cholesky(corr: np.ndarray) -> np.ndarray:
    """Lower-triangular Cholesky factor of the nearest positive-definite
    correlation matrix."""
    a = np.atleast_2d(np.asarray(corr, dtype=float))
    nvar = a.shape[0]
    if nvar == 0:
        return np.empty((0, 0))
    a = (a + a.T) / 2.0
    w, v = np.linalg.eigh(a)
    w = np.clip(w, 1e-10, None)
    a = (v * w) @ v.T
    d = np.sqrt(np.clip(np.diag(a), 1e-12, None))
    a = a / np.outer(d, d)        # renormalise to unit diagonal (a correlation)
    np.fill_diagonal(a, 1.0)
    for jitter in (0.0, 1e-10, 1e-8, 1e-6, 1e-4):
        try:
            return np.linalg.cholesky(a + jitter * np.eye(nvar))
        except np.linalg.LinAlgError:
            continue
    return np.eye(nvar)


def factor_decompose(corr: np.ndarray, group_ids: list[int]):
    """Single-factor-per-group + global-factor decomposition of ``corr``.
    """
    a = np.atleast_2d(np.asarray(corr, dtype=float))
    n = a.shape[0]
    groups = list(group_ids) if group_ids else [0] * n
    uniq = sorted(set(groups))
    gi = {g: i for i, g in enumerate(uniq)}
    K = 1 + len(uniq)  # column 0 = global, then one per group

    off = a[~np.eye(n, dtype=bool)] if n > 1 else np.array([0.0])
    g = math.sqrt(max(0.0, float(off.mean()) if off.size else 0.0))

    # mean within-group correlation per group (off-diagonal members only)
    within: dict[int, float] = {}
    for grp in uniq:
        idx = [i for i, gg in enumerate(groups) if gg == grp]
        if len(idx) > 1:
            sub = a[np.ix_(idx, idx)]
            vals = sub[~np.eye(len(idx), dtype=bool)]
            within[grp] = float(vals.mean())
        else:
            within[grp] = g * g  # lone member → no extra group co-movement

    loadings = np.zeros((n, K))
    idio = np.zeros(n)
    for j in range(n):
        b = math.sqrt(max(0.0, within[groups[j]] - g * g))
        loadings[j, 0] = g
        loadings[j, 1 + gi[groups[j]]] = b
        idio[j] = math.sqrt(max(1e-6, 1.0 - g * g - b * b))
    return loadings, np.ones(K), idio


# fat tails & price dynamics

def estimate_t_df(returns: np.ndarray) -> float:
    """Method-of-moments Student-t degrees of freedom for the copula: from the
    excess kurtosis κ of the (per-column standardised, pooled) returns,
    ``ν = 6/κ + 4`` (the t-distribution's kurtosis relation). Thin tails (κ≤0) →
    a large ν (≈ Gaussian). Clamped to ``[3, 100]``."""
    a = np.atleast_2d(np.asarray(returns, dtype=float))
    if a.shape[0] == 1 and returns.ndim == 1:
        a = a.T
    cols = []
    for j in range(a.shape[1]):
        c = a[:, j][np.isfinite(a[:, j])]
        if c.size > 3 and c.std() > 0:
            cols.append((c - c.mean()) / c.std())
    if not cols:
        return 100.0
    pooled = np.concatenate(cols)
    if pooled.size < 8:
        return 100.0
    kurt_excess = float(np.mean(pooled ** 4) - 3.0)
    if kurt_excess <= 1e-6:
        return 100.0
    return float(min(100.0, max(3.0, 6.0 / kurt_excess + 4.0)))


def fit_ar1(prices) -> tuple[float, float, float, float]:
    """Fit an AR(1)/Ornstein-Uhlenbeck process to a log-price series by OLS."""
    a = _clean_positive(prices)
    mu, sigma = lognormal_params(prices)
    if a.size < 4:
        x0 = math.log(a[-1]) if a.size else mu
        return 0.0, sigma, mu, x0
    x = np.log(a)
    rho, c = np.polyfit(x[:-1], x[1:], 1)        # x_t = c + rho·x_{t-1}
    rho = float(np.clip(rho, 0.0, 0.9999))
    phi = 1.0 - rho
    theta = c / (1.0 - rho) if abs(1.0 - rho) > 1e-9 else float(x.mean())
    resid = x[1:] - (c + rho * x[:-1])
    step_sigma = float(resid.std(ddof=1)) if resid.size > 1 else sigma
    return phi, step_sigma, float(theta), float(x[-1])


def garch_omega(step_sigma: float, alpha: float, beta: float) -> float:
    """GARCH(1,1)"""
    persist = max(1e-6, 1.0 - (alpha + beta))
    return max(1e-12, step_sigma * step_sigma * persist)
