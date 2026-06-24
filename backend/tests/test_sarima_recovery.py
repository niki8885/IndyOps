"""
Known-answer recovery for the native-style SARIMA estimator (services.sarima).

Rather than diff against statsmodels (not a dependency), we generate series from
*known* ARMA/SARMA processes and assert the CSS estimator recovers the
coefficients and that the auto-selected forecast beats the seasonal-naive
benchmark where it should. This is the language-independent correctness lock for
the Fortran port too (which agrees to ~1e-8, see the cross-check harness).
"""
import numpy as np

from app.services import sarima as S


def _arma(n, phi=0.0, theta=0.0, Phi=0.0, sp=7, seed=0, burn=200):
    rng = np.random.default_rng(seed)
    e = rng.normal(0, 1.0, n + burn)
    x = np.zeros(n + burn)
    for t in range(1, n + burn):
        ar = phi * x[t - 1] + (Phi * x[t - sp] if t >= sp else 0.0)
        x[t] = ar + e[t] + theta * e[t - 1]
    return x[burn:]


def _integrate(x, level=1000.0):
    return level + np.cumsum(x)


def test_recover_arima_111():
    y = _integrate(_arma(900, phi=0.6, theta=-0.4, seed=1))
    fit = S.sarima_fit(y, (1, 1, 1), (0, 0, 0))
    assert fit is not None
    assert abs(fit["phi"][0] - 0.6) < 0.15, fit["phi"]
    assert abs(fit["theta"][0] - (-0.4)) < 0.15, fit["theta"]


def test_recover_sarima_seasonal_ar():
    y = _integrate(_arma(1100, theta=-0.3, Phi=0.5, sp=7, seed=2))
    fit = S.sarima_fit(y, (0, 1, 1), (1, 0, 0))
    assert fit is not None
    assert abs(fit["theta"][0] - (-0.3)) < 0.12, fit["theta"]
    assert abs(fit["Phi"][0] - 0.5) < 0.12, fit["Phi"]


def test_forecast_beats_naive_on_arima():
    """On a clearly non-seasonal ARIMA series, auto-SARIMA must beat seasonal-naive."""
    y = _integrate(_arma(900, phi=0.6, theta=-0.4, seed=1))
    h, m = 30, 7
    tr, te = y[:-h], y[-h:]
    fc = S.f_sarima(tr, h)
    assert fc is not None
    snaive = np.array([tr[len(tr) - m + (i % m)] for i in range(h)])
    scale = np.mean(np.abs(tr[m:] - tr[:-m]))
    mase_sarima = np.mean(np.abs(fc - te)) / scale
    mase_naive = np.mean(np.abs(snaive - te)) / scale
    assert mase_sarima < mase_naive, (mase_sarima, mase_naive)


def test_stationarity_guard_rejects_explosive():
    """An explosive AR(1) coefficient must be rejected by the stationarity guard."""
    assert not S._stationary(np.array([1.05]), np.array([]))
    assert not S._stationary(np.array([]), np.array([1.2]))
    assert S._stationary(np.array([0.6]), np.array([0.5]))
