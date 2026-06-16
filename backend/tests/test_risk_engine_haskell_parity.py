"""
Parity: the Haskell risk-engine (haskell/risk-engine) must agree with the Python
oracle (services.profit_sim.rank_strategies) on the same candidate strategies.

The scoring is plain float arithmetic shared by both sides, so parity is **exact
on rank order** and bit-close on the score (cross-language float formatting).

Skipped automatically where the binary isn't built (RISK_ENGINE_BIN or the default
haskell/risk-engine/bin/risk-engine[.exe]).
"""
import pytest

from app.adapters import risk_engine
from app.services import profit_sim as ps

pytestmark = pytest.mark.skipif(not risk_engine.available(),
                                reason="risk-engine binary not built on this host")


def _items():
    return [
        ps.RankInput("A", 1000, 2.0, -50, 1000, 10, 0.10),
        ps.RankInput("B", 500, 0.5, -300, 500, 5, 0.40),
        ps.RankInput("C", 1200, 1.0, -200, 600, 8, 0.20),
        ps.RankInput("D", 950, 1.8, -80, 900, 9, 0.12),
    ]


WEIGHTS = {
    "default": None,
    "profit_only": {"expected_profit": 1.0, "sharpe_like": 0.0, "var5": 0.0,
                    "return_per_slot": 0.0, "return_per_time": 0.0, "prob_loss": 0.0},
    "risk_heavy": {"expected_profit": 0.5, "sharpe_like": 1.0, "var5": 2.0,
                   "return_per_slot": 0.0, "return_per_time": 0.0, "prob_loss": 2.0},
}


@pytest.mark.parametrize("wkey", list(WEIGHTS))
def test_haskell_matches_python(wkey):
    items = _items()
    weights = WEIGHTS[wkey]
    py = ps.rank_strategies(items, weights)
    hs, engine = risk_engine.rank(items, weights, prefer_native=True)

    assert engine == "haskell"
    # exact rank order + labels
    assert [(r.rank, r.label) for r in hs] == [(r.rank, r.label) for r in py]
    # scores agree to float-formatting precision
    for a, b in zip(hs, py):
        assert a.label == b.label
        assert abs(a.score - b.score) < 1e-9


def test_single_and_empty():
    one, _ = risk_engine.rank([ps.RankInput("solo", 1, 1, 1, 1, 1, 0.1)])
    assert one == [ps.RankedStrategy(rank=1, label="solo", score=0.0)]
    empty, _ = risk_engine.rank([])
    assert empty == []
