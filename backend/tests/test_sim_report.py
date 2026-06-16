"""PDF rendering for Monte-Carlo profit-simulation reports."""
from dataclasses import asdict

from app.services import profit_sim as ps
from app.services import sim_report_pdf as pdf


def _report(label, seed):
    hist = {
        1: ps.TypeHistory(buy=[95, 100, 105, 98, 102, 110, 90], sell=[100, 106, 110, 103, 108, 116, 95],
                          volume=[8000] * 7, last_buy=100),
        2: ps.TypeHistory(buy=[1900, 2000, 2100], sell=[1950, 2050, 2150, 2000, 2100],
                          volume=[3000] * 5, last_sell=2050),
    }
    req = ps.request_from_legs(label, [(1, 10)], 2, 5, hist, 250.0, 7200,
                               ps.SimParams(n_iterations=5000, seed=seed, dist_mode=0),
                               broker_fee_pct=3.6, sales_tax_pct=2.0)
    res = ps.simulate(req)
    return {"label": label, "source": "chain", "product_name": "Widget", "engine": "python",
            "created_at": "2026-06-16T12:00:00", "params": asdict(req.params),
            "metrics": asdict(res.metrics)}, res


def test_render_run_pdf_is_valid():
    report, _ = _report("Widget T2", 7)
    out = pdf.render_run_pdf(report)
    assert out[:4] == b"%PDF" and len(out) > 2000


def test_render_rollup_pdf_with_ranking():
    r1, res1 = _report("strategy-A", 7)
    r2, res2 = _report("strategy-B", 9)
    ranked = ps.rank_strategies([ps.RankInput.from_metrics("strategy-A", res1.metrics),
                                 ps.RankInput.from_metrics("strategy-B", res2.metrics)])
    out = pdf.render_rollup_pdf("Project Alpha", [r1, r2], [asdict(r) for r in ranked])
    assert out[:4] == b"%PDF" and len(out) > 3000


def test_render_run_pdf_tolerates_missing_histogram():
    report, _ = _report("no-hist", 1)
    report["metrics"]["hist_counts"] = []
    report["metrics"]["hist_edges"] = []
    out = pdf.render_run_pdf(report)         # must not raise without a chart
    assert out[:4] == b"%PDF"
