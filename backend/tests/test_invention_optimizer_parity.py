"""
Parity: the Haskell invention-optimizer (haskell/invention-optimizer) must agree
with the Python oracle (services.invention_opt.optimize) on the same products ×
decryptors — exact rank order + labels, bit-close score.

Skipped where the binary isn't built (INVENTION_OPTIMIZER_BIN or the default
haskell/invention-optimizer/bin/invention-optimizer[.exe]).
"""
import pytest

from app.adapters import invention_optimizer as opt
from app.services import invention_opt as core
from app.services.invention import DECRYPTORS, Material
from app.services.invention_opt import OptInput

pytestmark = pytest.mark.skipif(not opt.available(),
                                reason="invention-optimizer binary not built on this host")


def _products():
    return [
        OptInput(product_type_id=100, product_name="Widget II", base_prob=0.34, base_runs=10,
                 units_per_run=1, datacore_cost=500_000, invention_install_cost=10_000,
                 manuf_install_per_run=5_000, sell_per_unit=4_000_000,
                 materials=[Material(100, 50.0), Material(1, 1_000_000.0)], mat_extra_mult=1.0,
                 encryption=5, sci1=5, sci2=4),
        OptInput(product_type_id=200, product_name="Gadget II", base_prob=0.26, base_runs=1,
                 units_per_run=1, datacore_cost=900_000, invention_install_cost=20_000,
                 manuf_install_per_run=8_000, sell_per_unit=60_000_000,
                 materials=[Material(50, 2_000.0), Material(3, 500_000.0)], mat_extra_mult=1.0,
                 encryption=4, sci1=5, sci2=5),
    ]


_PRICES = {d.type_id: (d.type_id % 100) * 10_000 + 100_000 for d in DECRYPTORS if d.type_id}

WEIGHTS = {
    "default": None,
    "profit_only": {"profit_per_run": 1.0, "margin_pct": 0.0, "profit_per_unit": 0.0,
                    "cost_per_bpc": 0.0, "probability": 0.0},
    "cost_heavy": {"profit_per_run": 0.5, "margin_pct": 1.0, "profit_per_unit": 0.0,
                   "cost_per_bpc": 2.0, "probability": 1.0},
}


@pytest.mark.parametrize("wkey", list(WEIGHTS))
def test_haskell_matches_python(wkey):
    prods = _products()
    weights = WEIGHTS[wkey]
    py = core.optimize(prods, DECRYPTORS, _PRICES, weights)
    hs, engine = opt.optimize(prods, DECRYPTORS, _PRICES, weights, prefer_native=True)

    assert engine == "haskell"
    assert [(r["rank"], r["label"]) for r in hs] == [(r["rank"], r["label"]) for r in py]
    for a, b in zip(hs, py):
        assert a["label"] == b["label"]
        assert abs(a["score"] - b["score"]) < 1e-9


def test_single_and_empty():
    one = _products()[:1]
    ranked, engine = opt.optimize(one, DECRYPTORS, _PRICES)
    assert engine == "haskell"
    assert len(ranked) == len(DECRYPTORS)          # one product × all decryptors
    assert ranked[0]["rank"] == 1
    empty, _ = opt.optimize([], DECRYPTORS, _PRICES)
    assert empty == []
