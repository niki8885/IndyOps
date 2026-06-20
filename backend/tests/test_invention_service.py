"""Pure invention-math tests: probability, decryptor effects, candidate economics,
and the optimizer ranking oracle. No DB/web."""
from app.services import invention as inv
from app.services import invention_opt as opt
from app.services.invention import Material, DECRYPTOR_BY_NAME


def test_probability_formula_all_v():
    # 0.34 × (1 + 10/30 + 5/40) × 1.2 (Accelerant +20%) ≈ 0.595
    p = inv.success_probability(0.34, encryption_lvl=5, sci1_lvl=5, sci2_lvl=5, prob_mod=20)
    assert abs(p - 0.34 * (1 + 10 / 30 + 5 / 40) * 1.2) < 1e-12
    # clamped to ≤ 1
    assert inv.success_probability(0.9, 5, 5, 5, 90) == 1.0


def test_evaluate_decryptor_effects():
    acc = DECRYPTOR_BY_NAME["Accelerant"]   # +1 run, +2 ME, +10 TE
    row = inv.evaluate(
        base_prob=0.34, base_runs=10, units_per_run=1,
        datacore_cost=500_000, decryptor_price=800_000, invention_install_cost=10_000,
        manuf_install_per_run=5_000, sell_per_unit=4_000_000,
        materials=[Material(100, 50.0)], mat_extra_mult=1.0,
        encryption=5, sci1=5, sci2=5, decryptor=acc)
    assert row["bpc_runs"] == 11 and row["bpc_me"] == 4 and row["bpc_te"] == 14
    # cost/attempt = datacores + decryptor + install
    assert row["cost_per_attempt"] == 500_000 + 800_000 + 10_000
    # cost/bpc = cost/attempt ÷ probability
    assert abs(row["cost_per_bpc"] - row["cost_per_attempt"] / row["probability"]) < 1e-6


def test_no_decryptor_base_me_te():
    row = inv.evaluate(
        base_prob=0.3, base_runs=10, units_per_run=1,
        datacore_cost=100_000, decryptor_price=0, invention_install_cost=0,
        manuf_install_per_run=0, sell_per_unit=1_000_000,
        materials=[], mat_extra_mult=1.0,
        encryption=4, sci1=4, sci2=4, decryptor=DECRYPTOR_BY_NAME["No Decryptor"])
    assert row["bpc_me"] == 2 and row["bpc_te"] == 4 and row["bpc_runs"] == 10


def test_optimizer_ranks_and_is_deterministic():
    products = [
        opt.OptInput(product_type_id=1, product_name="A", base_prob=0.34, base_runs=10,
                     units_per_run=1, datacore_cost=500_000, invention_install_cost=10_000,
                     manuf_install_per_run=5_000, sell_per_unit=4_000_000,
                     materials=[Material(100, 50.0)], mat_extra_mult=1.0,
                     encryption=5, sci1=5, sci2=5),
    ]
    prices = {d.type_id: 200_000 for d in inv.DECRYPTORS if d.type_id}
    ranked = opt.optimize(products, inv.DECRYPTORS, prices)
    assert len(ranked) == len(inv.DECRYPTORS)            # 1 product × 9 decryptors
    assert [r["rank"] for r in ranked] == list(range(1, len(ranked) + 1))
    scores = [r["score"] for r in ranked]
    assert scores == sorted(scores, reverse=True)
    # rerun → identical order (deterministic)
    assert [r["label"] for r in opt.optimize(products, inv.DECRYPTORS, prices)] == [r["label"] for r in ranked]
