"""
Parity: the native ``portfolio-opt`` Fortran engine must agree with the Python
oracle (``services.portfolio.optimize``) on the same request.

Unlike the Monte-Carlo engines, the optimiser is **deterministic** (water-filling
on a diagonal-Sigma simplex), so native and oracle agree to numerical precision —
the only gap is the full-precision text round-trip of the weights/metrics.

Skipped automatically where the binary isn't built (PORTFOLIO_OPT_BIN or the default
fortran/analytics-engine/bin/portfolio-opt[.exe]).
"""
import pytest

from app.adapters import portfolio as eng
from app.services import portfolio as core

pytestmark = pytest.mark.skipif(not eng.available(),
                                reason="portfolio-opt binary not built on this host")

ABS = 1e-9

CASES = [
    ([0.20, 0.10, 0.05], [0.30, 0.15, 0.05], 8.0),
    ([0.12, 0.12, 0.12, 0.12], [0.1, 0.2, 0.3, 0.4], 5.0),
    ([0.30, 0.08], [0.40, 0.10], 1.0),          # return-hungry (small lambda)
    ([0.05, 0.05], [0.0, 0.20], 8.0),           # one near-riskless asset
    ([-0.02, 0.04, 0.09, 0.15, 0.01], [0.2, 0.18, 0.25, 0.5, 0.12], 12.0),
    ([0.10], [0.2], 8.0),                        # single asset
]


@pytest.mark.parametrize("mu,sigma,lam", CASES)
def test_native_matches_oracle(mu, sigma, lam):
    w_native, m_native, engine = eng.optimize_weights(mu, sigma, lam, prefer_native=True)
    assert engine == "fortran"
    w_oracle, m_oracle = core.optimize(mu, sigma, lam)

    assert len(w_native) == len(w_oracle)
    for a, b in zip(w_native, w_oracle):
        assert abs(a - b) < ABS
    for key in ("exp_return", "variance", "stddev"):
        assert abs(m_native[key] - m_oracle[key]) < ABS
