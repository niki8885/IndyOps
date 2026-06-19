from app.services import scenario_report_pdf as spdf


def _metrics(ep=1000.0):
    return {
        "n_iterations": 2000, "expected_profit": ep, "median_profit": ep, "std": 300.0,
        "cv": 0.3, "var5": -100.0, "var1": -250.0, "cvar5": -180.0, "worst1": -400.0,
        "prob_loss": 0.12, "percentiles": {"p1": -250, "p5": -100, "p25": 400, "p50": ep,
                                           "p75": 1500, "p95": 2200, "p99": 2600},
        "best": 3000.0, "worst": -500.0,
        "hist_counts": [1, 5, 20, 40, 30, 10, 4] + [0] * 33,
        "hist_edges": [float(i) for i in range(41)],
        "breakdown": {"material_cost": {"mean": 4000.0, "p5": 3800, "p50": 4000, "p95": 4200},
                      "revenue": {"mean": 5200.0, "p5": 5000, "p50": 5200, "p95": 5400},
                      "taxes_fees": {"mean": 200.0, "p5": 190, "p50": 200, "p95": 210},
                      "logistics": {"mean": 0.0, "p5": 0, "p50": 0, "p95": 0}},
        "time_mean_h": 0.17, "time_median_h": 0.17, "time_p95_h": 0.17, "time_per_job_h": 0.17,
        "time_hist_counts": [2000] + [0] * 39, "time_hist_edges": [float(i) for i in range(41)],
        "sharpe_like": 3.3, "risk_adjusted": 700.0, "return_per_slot": ep, "return_per_time": ep,
    }


def _report():
    outcomes = []
    for key, name, cat, dprof in [
        ("market_shock_up", "Market Shock (up)", "exogenous", 400.0),
        ("resource_shortage", "Resource Shortage", "exogenous", -300.0),
        ("logistics_disruption", "Logistics Disruption", "logistics", -150.0),
        ("jita_plus_20", "What if Jita +20%?", "counterfactual", 600.0),
    ]:
        m = _metrics(1000.0 + dprof)
        outcomes.append({
            "key": key, "name": name, "category": cat, "params": {},
            "metrics": m,
            "comparison": {"abs_profit_change": dprof, "pct_profit_change": dprof / 1000.0,
                           "std_change": 10.0, "var5_change": -20.0, "prob_loss_change": 0.05,
                           "roi_baseline": 0.2, "roi_scenario": 0.2 + dprof / 5000.0,
                           "roi_change": dprof / 5000.0, "viable": dprof > -300.0},
        })
    return {
        "label": "Widget", "source": "chain", "product_name": "Widget",
        "target_type_id": 1, "engine": "python", "created_at": "2026-06-19T00:00:00",
        "params": {"n_iterations": 2000}, "baseline": _metrics(1000.0), "outcomes": outcomes,
        "ranking": [{"rank": 1, "label": "What if Jita +20%?", "score": 2.1},
                    {"rank": 2, "label": "● Baseline", "score": 0.0}],
    }


def test_render_scenario_pdf():
    pdf = spdf.render_scenario_pdf(_report())
    assert pdf[:4] == b"%PDF" and len(pdf) > 1500


def test_render_product_pdf_combines_runs_and_analyses():
    sim_run = {"label": "Widget", "source": "chain", "product_name": "Widget",
               "target_type_id": 1, "engine": "python", "created_at": "2026-06-19T00:00:00",
               "params": {}, "metrics": _metrics(1200.0)}
    pdf = spdf.render_product_pdf("Widget", [sim_run], [_report()])
    assert pdf[:4] == b"%PDF" and len(pdf) > 2000


def test_render_scenario_pdf_handles_empty_outcomes():
    rep = _report()
    rep["outcomes"] = []
    rep["ranking"] = []
    pdf = spdf.render_scenario_pdf(rep)
    assert pdf[:4] == b"%PDF"


def test_share_code_renders_qr_and_ref():
    from app.services import sim_report_pdf as mc
    assert len(mc.job_ref("IJ1.somecode")) == 8
    plain = spdf.render_scenario_pdf(_report())
    rep = _report()
    rep["share_code"] = "13079952"
    rep["share_url"] = "https://example.test/manufacturing?job=13079952"
    withqr = spdf.render_scenario_pdf(rep)
    assert withqr[:4] == b"%PDF"
    assert len(withqr) > len(plain)   # the QR + barcode share block add content
