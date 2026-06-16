from __future__ import annotations
import math
import numpy as np

# Acklam inverse normal CDF (|err| < 1.15e-9)
_A = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
      1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
_B = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
      6.680131188771972e+01, -1.328068155288572e+01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
      -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
      3.754408661907416e+00)
_PLOW, _PHIGH = 0.02425, 1.0 - 0.02425


def norm_ppf(p):
    """Inverse standard-normal CDF, elementwise. Clamps p into (0,1)."""
    p = np.clip(np.asarray(p, dtype=float), 1e-15, 1.0 - 1e-15)
    out = np.empty_like(p)

    lo = p < _PLOW
    hi = p > _PHIGH
    mid = ~(lo | hi)

    q = np.sqrt(-2.0 * np.log(p[lo]))
    out[lo] = (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
              ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)

    q = np.sqrt(-2.0 * np.log(1.0 - p[hi]))
    out[hi] = -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
              ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)

    q = p[mid] - 0.5
    r = q * q
    out[mid] = (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / \
               (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0)
    return out


# regularised incomplete beta Iₓ(a,b) -> Student-t CDF
def _betacf(a: float, b: float, x: np.ndarray, iters: int = 200) -> np.ndarray:
    """Continued fraction for the incomplete beta (Lentz). ``a,b`` scalar, ``x``
    array. Fixed iteration count (vectorised; x=ν/(ν+t²) converges fast)."""
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = np.ones_like(x)
    d = 1.0 - qab * x / qap
    d = np.where(np.abs(d) < tiny, tiny, d)
    d = 1.0 / d
    h = d.copy()
    for m in range(1, iters + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = np.where(np.abs(d) < tiny, tiny, d)
        c = 1.0 + aa / c
        c = np.where(np.abs(c) < tiny, tiny, c)
        d = 1.0 / d
        h = h * d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = np.where(np.abs(d) < tiny, tiny, d)
        c = 1.0 + aa / c
        c = np.where(np.abs(c) < tiny, tiny, c)
        d = 1.0 / d
        h = h * d * c
    return h


def _betai(a: float, b: float, x: np.ndarray) -> np.ndarray:
    """Regularised incomplete beta Iₓ(a,b), ``a,b`` scalar, ``x`` array."""
    x = np.clip(np.asarray(x, dtype=float), 0.0, 1.0)
    lge = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    safe = (x > 0.0) & (x < 1.0)
    bt = np.where(safe, np.exp(lge + a * np.log(np.where(safe, x, 0.5))
                               + b * np.log(np.where(safe, 1.0 - x, 0.5))), 0.0)
    cond = x < (a + 1.0) / (a + b + 2.0)
    return np.where(cond, bt * _betacf(a, b, x) / a,
                    1.0 - bt * _betacf(b, a, 1.0 - x) / b)


def student_t_cdf(t, df: float) -> np.ndarray:
    """CDF of the Student-t distribution with ``df`` degrees of freedom, elementwise.
    ``T_ν(t) = 1 − ½·I_x(ν/2, ½)`` for t≥0 (symmetric), ``x = ν/(ν+t²)``."""
    t = np.asarray(t, dtype=float)
    x = df / (df + t * t)
    ib = _betai(df / 2.0, 0.5, x)
    return np.where(t >= 0.0, 1.0 - 0.5 * ib, 0.5 * ib)
