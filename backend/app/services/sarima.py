"""Native SARIMA(p,d,q)(P,D,Q)_s — pure numpy (IO-49 phase 2, oracle).

Conditional-Sum-of-Squares estimation: difference the series, expand the
multiplicative seasonal AR/MA polynomials by convolution, then minimise the
conditional residual SSE with a hand-rolled Nelder-Mead (no scipy). AR start
values come from an OLS fit; MA/seasonal start at zero. Order is auto-selected by
AICc over a small candidate grid (auto-ARIMA-lite). d,D ∈ {0,1}, s=7.

This is the oracle the Fortran port must match; correctness is checked by
known-answer recovery on synthetic processes (test_sarima_recovery.py) rather than
against statsmodels, keeping the stack dependency-free.
"""
from __future__ import annotations
from typing import Optional

import numpy as np

SEASON = 7

# (order, seasonal_order) candidate grid — common shapes for daily market series
_ORDERS = (
    ((1, 1, 0), (0, 0, 0)),
    ((0, 1, 1), (0, 0, 0)),
    ((1, 1, 1), (0, 0, 0)),
    ((2, 1, 0), (0, 0, 0)),
    ((0, 1, 1), (1, 0, 0)),
    ((1, 1, 0), (1, 0, 0)),
    ((1, 1, 1), (1, 0, 0)),
    ((0, 1, 1), (0, 0, 1)),
    ((0, 1, 1), (1, 0, 1)),
)


# ── polynomial helpers (B = backshift) ──

def _full_ar(phi: np.ndarray, Phi: np.ndarray, s: int) -> np.ndarray:
    """Φ(B)·Φ_s(B^s) as [1, a1, a2, …] (AR poly, leading 1, minus-signed coeffs)."""
    a = np.r_[1.0, -np.asarray(phi, float)] if len(phi) else np.array([1.0])
    if len(Phi):
        asn = np.zeros(s * len(Phi) + 1); asn[0] = 1.0
        for k, c in enumerate(Phi):
            asn[(k + 1) * s] = -c
    else:
        asn = np.array([1.0])
    return np.convolve(a, asn)


def _full_ma(theta: np.ndarray, Theta: np.ndarray, s: int) -> np.ndarray:
    """Θ(B)·Θ_s(B^s) as [1, b1, b2, …] (MA poly, leading 1, plus-signed coeffs)."""
    m = np.r_[1.0, np.asarray(theta, float)] if len(theta) else np.array([1.0])
    if len(Theta):
        msn = np.zeros(s * len(Theta) + 1); msn[0] = 1.0
        for k, c in enumerate(Theta):
            msn[(k + 1) * s] = c
    else:
        msn = np.array([1.0])
    return np.convolve(m, msn)


def _difference(y: np.ndarray, d: int, D: int, s: int) -> np.ndarray:
    u = np.asarray(y, float)
    for _ in range(d):
        u = np.diff(u)
    for _ in range(D):
        u = u[s:] - u[:-s]
    return u


def _css_resid(w: np.ndarray, AF: np.ndarray, MF: np.ndarray) -> np.ndarray:
    """Conditional residuals e_t: AF(B) w_t = MF(B) e_t, presample = 0."""
    n = len(w)
    arpart = np.convolve(w, AF)[:n]          # = w_t + Σ_{i≥1} AF[i] w_{t-i}
    pMA = len(MF) - 1
    if pMA == 0:
        return arpart
    e = np.zeros(n)
    for t in range(n):
        acc = arpart[t]
        for j in range(1, pMA + 1):
            if t - j >= 0:
                acc -= MF[j] * e[t - j]
        e[t] = acc
    return e


def _stationary(phi, Phi):
    """Multiplicative-AR stationarity in closed form (roots factor): non-seasonal
    AR(p≤2) and seasonal AR(P≤1). Guards against explosive multi-step forecasts."""
    lim = 0.999
    if len(phi) == 1 and abs(phi[0]) >= lim:
        return False
    if len(phi) == 2:
        a1, a2 = phi
        if not (abs(a2) < lim and a1 + a2 < lim and a2 - a1 < lim):
            return False
    if len(phi) >= 3:
        return False
    if len(Phi) >= 1 and abs(Phi[0]) >= lim:
        return False
    return True


def _unpack(params, p, q, P, Q):
    phi = np.asarray(params[:p])
    theta = np.asarray(params[p:p + q])
    Phi = np.asarray(params[p + q:p + q + P])
    Theta = np.asarray(params[p + q + P:p + q + P + Q])
    return phi, theta, Phi, Theta


def _css(w, params, p, q, P, Q, s):
    phi, theta, Phi, Theta = _unpack(params, p, q, P, Q)
    AF = _full_ar(phi, Phi, s)
    MF = _full_ma(theta, Theta, s)
    e = _css_resid(w, AF, MF)
    warmup = len(AF) - 1
    if warmup >= len(e):
        return 1e18
    sse = float(np.sum(e[warmup:] ** 2))
    if not np.isfinite(sse):
        return 1e18
    return sse


def _ar_ols_init(w, p):
    """OLS AR(p) on the (differenced, ~zero-mean) series → φ start values."""
    if p == 0 or len(w) <= p + 1:
        return np.zeros(p)
    rows = len(w) - p
    X = np.empty((rows, p))
    for k in range(1, p + 1):
        X[:, k - 1] = w[p - k:p - k + rows]
    coef, *_ = np.linalg.lstsq(X, w[p:], rcond=None)
    return np.clip(coef, -0.95, 0.95)


def _nelder_mead(f, x0, iters=140, step=0.15):
    n = len(x0)
    if n == 0:
        return np.asarray(x0, float)
    x0 = np.asarray(x0, float)
    simplex = [x0.copy()]
    for i in range(n):
        xi = x0.copy()
        xi[i] += step if x0[i] == 0 else step * (1 + abs(x0[i]))
        simplex.append(xi)
    fv = [f(x) for x in simplex]
    a, g, r, sg = 1.0, 2.0, 0.5, 0.5
    for _ in range(iters):
        idx = np.argsort(fv)
        simplex = [simplex[i] for i in idx]
        fv = [fv[i] for i in idx]
        cent = np.mean(simplex[:-1], axis=0)
        xr = cent + a * (cent - simplex[-1]); fr = f(xr)
        if fr < fv[0]:
            xe = cent + g * (xr - cent); fe = f(xe)
            simplex[-1], fv[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < fv[-2]:
            simplex[-1], fv[-1] = xr, fr
        else:
            xc = cent + r * (simplex[-1] - cent); fc = f(xc)
            if fc < fv[-1]:
                simplex[-1], fv[-1] = xc, fc
            else:
                best = simplex[0]
                for i in range(1, n + 1):
                    simplex[i] = best + sg * (simplex[i] - best)
                    fv[i] = f(simplex[i])
    idx = int(np.argmin(fv))
    return simplex[idx]


def sarima_fit(y: np.ndarray, order, sorder, s: int = SEASON) -> Optional[dict]:
    """Estimate one (order, seasonal_order). Returns fit dict or None if infeasible."""
    p, d, q = order
    P, D, Q = sorder
    w = _difference(y, d, D, s)
    nparam = p + q + P + Q
    min_len = max(2 * s, p + s * P + q + s * Q) + 5
    if len(w) < min_len:
        return None
    x0 = np.concatenate([_ar_ols_init(w, p), np.zeros(q + P + Q)])
    if nparam > 0:
        params = _nelder_mead(lambda th: _css(w, th, p, q, P, Q, s), x0)
    else:
        params = np.zeros(0)
    phi, theta, Phi, Theta = _unpack(params, p, q, P, Q)
    if not _stationary(phi, Phi):
        return None                                  # reject explosive AR
    AF = _full_ar(phi, Phi, s)
    MF = _full_ma(theta, Theta, s)
    e = _css_resid(w, AF, MF)
    warmup = len(AF) - 1
    valid = e[warmup:]
    nobs = len(valid)
    if nobs <= nparam + 1:
        return None
    sigma2 = float(np.mean(valid ** 2))
    k = nparam + 1
    if sigma2 <= 0 or not np.isfinite(sigma2):
        return None
    aic = nobs * np.log(sigma2) + 2 * k
    aicc = aic + (2 * k * (k + 1)) / max(1, nobs - k - 1)
    return {"order": order, "sorder": sorder, "params": params, "AF": AF, "MF": MF,
            "resid": e, "sigma2": sigma2, "aicc": float(aicc),
            "phi": phi, "theta": theta, "Phi": Phi, "Theta": Theta}


def _integrate_forecast(y, wf, d, D, s):
    """Undo seasonal then non-seasonal differencing (d,D ∈ {0,1})."""
    y = np.asarray(y, float)
    u = y.copy()
    for _ in range(d):
        u = np.diff(u)
    if D == 1:
        u_ext = list(u)
        uf = []
        for k in range(len(wf)):
            uf.append(wf[k] + u_ext[len(u) + k - s])
            u_ext.append(uf[-1])
        uf = np.array(uf)
    else:
        uf = np.asarray(wf, float)
    if d == 1:
        y_ext = list(y)
        yf = []
        for k in range(len(uf)):
            yf.append(y_ext[len(y) + k - 1] + uf[k])
            y_ext.append(yf[-1])
        return np.array(yf)
    return uf


def sarima_forecast_from_fit(y, fit, h, s: int = SEASON) -> np.ndarray:
    d, D = fit["order"][1], fit["sorder"][1]
    AF, MF, e = fit["AF"], fit["MF"], fit["resid"]
    w = _difference(y, d, D, s)
    pAR, pMA = len(AF) - 1, len(MF) - 1
    w_ext = list(w)
    ne = len(e)
    wf = []
    for k in range(h):
        t = len(w) + k
        acc = 0.0
        for i in range(1, pAR + 1):
            acc -= AF[i] * w_ext[t - i]
        for j in range(1, pMA + 1):
            ej = e[t - j] if 0 <= t - j < ne else 0.0
            acc += MF[j] * ej
        wf.append(acc); w_ext.append(acc)
    return _integrate_forecast(y, np.array(wf), d, D, s)


def _mase(train, fc, act, m):
    scale = float(np.mean(np.abs(train[m:] - train[:-m]))) if len(train) > m else 0.0
    if scale <= 0 or not np.isfinite(scale):
        return float("inf")
    return float(np.mean(np.abs(np.asarray(fc) - np.asarray(act)))) / scale


def _holdout_score(y, order, sorder, h, s):
    """MASE of a true out-of-sample forecast — selects for forecast skill, so an
    over-fit order whose multi-step forecast diverges is rejected (huge MASE)."""
    tr, te = y[:-h], y[-h:]
    fit = sarima_fit(tr, order, sorder, s)
    if fit is None:
        return float("inf")
    fc = sarima_forecast_from_fit(tr, fit, h, s)
    if not np.all(np.isfinite(fc)):
        return float("inf")
    return _mase(tr, fc, te, s)


def auto_select(y: np.ndarray, s: int = SEASON, h: Optional[int] = None) -> Optional[dict]:
    """Fit the candidate grid; pick the order by out-of-sample MASE (AICc only when
    the series is too short to hold out). Returns the full-data refit of the winner."""
    if h is None:
        h = min(30, max(7, len(y) // 6))
    can_holdout = len(y) > h + max(2 * s, 10) + 5
    best, best_key = None, float("inf")
    for order, sorder in _ORDERS:
        fit = sarima_fit(y, order, sorder, s)
        if fit is None:
            continue
        key = _holdout_score(y, order, sorder, h, s) if can_holdout else fit["aicc"]
        if np.isfinite(key) and key < best_key:
            best, best_key = fit, key
    return best


def f_sarima(y: np.ndarray, h: int, s: int = SEASON) -> Optional[np.ndarray]:
    """Auto-SARIMA point forecast of length h, or None if nothing fits / diverges."""
    fit = auto_select(y, s, h)
    if fit is None:
        return None
    fc = sarima_forecast_from_fit(y, fit, h, s)
    if not np.all(np.isfinite(fc)):
        return None
    return fc
