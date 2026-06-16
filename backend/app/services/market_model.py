"""
Market-distribution & correlation estimation for the Monte-Carlo profit simulator.

Pure numpy/stdlib — no ORM, FastAPI or requests (see [[indyops-service-layering]]).
Turns raw price/volume history into the numeric inputs the simulation core needs:

* per-variable marginals — lognormal ``(mu, sigma)`` of log-price, and a
  fixed-resolution **empirical quantile grid** (so the engine can sample any
  historical distribution by linear interpolation, with a rectangular wire format);
* the cross-variable dependency — a correlation matrix and its **Cholesky** factor
  (Option A), or a **factor-model** decomposition (Option B): per-group + global
  loadings reproducing the block structure of the empirical correlation.

The same reductions feed both the Python oracle (``services.profit_sim``) and,
through the adapter, the native Fortran engine — so the two stay in parity.
"""
from __future__ import annotations

import math

import numpy as np

QGRID_POINTS = 101  # quantile-function resolution: percentiles 0,1,…,100


# ── marginals ─────────────────────────────────────────────────────────────────

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


# ── cross-variable dependency ───────────────────────────────────────────────────

def align_returns(price_columns: list[list[float]]) -> np.ndarray:
    """Tail-align equal-purpose price series to the shortest length and return the
    matrix of log-returns ``[T-1 × n]``. Rows with any non-finite return are
    dropped, so the result is clean for a correlation estimate. Empty when fewer
    than two aligned points are available."""
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
    """Pearson correlation of the columns of ``returns``. Falls back to the
    identity (independent) when there is too little data or a column is constant.
    ``n`` overrides the output size when ``returns`` is empty."""
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
    correlation matrix. Clips negative eigenvalues, renormalises the diagonal back
    to 1, and adds a small jitter if needed — so it never raises on a noisy
    empirical matrix. ``z = L·ε`` then has the (repaired) correlation."""
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

    A pragmatic, data-driven realisation of the spec's factor model (mineral / T2 /
    regional / industry drivers): each variable ``j`` loads on a **global** factor
    (industry-wide co-movement) and on **one group factor** (its market class), with
    the remainder idiosyncratic. Loadings are set so the implied correlation matches
    the empirical *average* within-group and cross-group correlation:

      * global loading ``g = sqrt(max(0, mean off-diagonal corr across all))``
      * group loading  ``b_G = sqrt(max(0, mean within-group corr_G − g²))``
      * idiosyncratic   ``s_j = sqrt(max(ε, 1 − g² − b_{G(j)}²))``

    Returns ``(loadings [n × K], factor_sigma [K], idio_sigma [n])`` where column 0
    is the global factor and the rest are the (ordered, distinct) group factors.
    By construction each row's variances sum to 1, so ``z_j`` is unit-variance.
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
