"""
PDF rendering for Scenario Simulation analyses (IO-23).

Mirrors ``sim_report_pdf`` (reportlab, pure over plain dicts) and reuses its
helpers/style. Two documents, analogous to the Monte-Carlo pair:

* ``render_scenario_pdf`` — one scenario analysis: baseline metrics, the
  scenario-vs-baseline comparison table (grouped by category), the risk-adjusted
  ranking, and a sensitivity tornado;
* ``render_product_pdf`` — the combined 'whole product' report: every Monte-Carlo
  run and every scenario analysis for one product in a single document.
"""
from __future__ import annotations

import io
from typing import Optional

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, SimpleDocTemplate, Spacer

from app.services.sim_report_pdf import (
    _HEAD, _h, _isk, _num, _p, _pct, _profit_histogram, _run_story, _share_block, _table,
)

_CATEGORY_LABEL = {
    "exogenous": "Exogenous (market)",
    "logistics": "Logistics",
    "demand": "Market demand",
    "counterfactual": "Counterfactual",
    "endogenous": "Endogenous (decisions)",
    "composite": "Composite stress test",
}


def _signed_isk(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return ("+" if x >= 0 else "") + _isk(x)


def _signed_pct(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return ("+" if x >= 0 else "") + f"{x * 100:.1f}%"


# ── comparison table ──────────────────────────────────────────────────────────

def _comparison_table(report: dict):
    base = report.get("baseline", {})
    outcomes = report.get("outcomes", [])
    rows = [["Scenario", "Category", "E[Profit]", "Δ Profit", "Δ %", "σ", "VaR 5%",
             "P(loss)", "ROI Δ", "Viable"]]
    base_row = [
        "● Baseline", "—", _isk(base.get("expected_profit")), "—", "—",
        _isk(base.get("std")), _isk(base.get("var5")), _pct(base.get("prob_loss")),
        "—", "✓" if base.get("expected_profit", 0) > 0 else "✗",
    ]
    rows.append(base_row)
    # sort by category (catalog grouping) then by profit impact
    order = sorted(outcomes, key=lambda o: (o.get("category", ""),
                                            -(o.get("comparison", {}).get("abs_profit_change", 0))))
    for o in order:
        m = o.get("metrics", {})
        c = o.get("comparison", {})
        rows.append([
            o.get("name", o.get("key", "—")),
            _CATEGORY_LABEL.get(o.get("category", ""), o.get("category", "—")),
            _isk(m.get("expected_profit")),
            _signed_isk(c.get("abs_profit_change")),
            _signed_pct(c.get("pct_profit_change")),
            _isk(m.get("std")),
            _isk(m.get("var5")),
            _pct(m.get("prob_loss")),
            _signed_pct(c.get("roi_change")),
            "✓" if c.get("viable") else "✗",
        ])
    widths = [38 * mm, 26 * mm, 19 * mm, 19 * mm, 13 * mm, 18 * mm, 18 * mm, 14 * mm, 13 * mm, 12 * mm]
    return _table(rows, col_widths=widths)


def _ranking_table(ranked: list[dict]):
    rows = [["Rank", "Strategy / scenario", "Composite score"]]
    for r in ranked:
        rows.append([str(r.get("rank")), r.get("label", "—"), _num(r.get("score"))])
    return _table(rows, col_widths=[18 * mm, 120 * mm, 35 * mm])


def _sensitivity_tornado(report: dict, width=170 * mm, height=70 * mm) -> Optional[Drawing]:
    """Horizontal bars of each scenario's % profit change vs baseline, sorted by
    magnitude — the classic tornado sensitivity view."""
    outcomes = report.get("outcomes", [])
    items = [(o.get("name", o.get("key", "")),
             float(o.get("comparison", {}).get("pct_profit_change", 0.0) or 0.0))
             for o in outcomes]
    items = [it for it in items if it[0]]
    if not items:
        return None
    items.sort(key=lambda t: abs(t[1]))   # smallest→largest (chart draws bottom→top)
    items = items[-14:]                    # cap rows so labels stay legible
    names = [it[0] for it in items]
    vals = [it[1] * 100.0 for it in items]
    d = Drawing(width, height)
    chart = HorizontalBarChart()
    chart.x, chart.y = 52 * mm, 6 * mm
    chart.width, chart.height = width - 60 * mm, height - 10 * mm
    chart.data = [vals]
    chart.bars[0].fillColor = _HEAD
    chart.bars[0].strokeColor = None
    chart.categoryAxis.categoryNames = names
    chart.categoryAxis.labels.fontSize = 6.5
    chart.categoryAxis.labels.boxAnchor = "e"
    chart.categoryAxis.labels.dx = -2
    chart.valueAxis.labels.fontSize = 6
    chart.valueAxis.valueStep = None
    d.add(chart)
    d.add(String(width - 6 * mm, height - 4 * mm, "Δ profit vs baseline (%)",
                 fontSize=7, textAnchor="end", fillColor=colors.HexColor("#555555")))
    return d


# ── per-analysis story ────────────────────────────────────────────────────────

def _scn_exec(report: dict) -> list:
    """Headline: baseline verdict + best/worst scenario + how many stay viable."""
    base = report.get("baseline", {})
    outs = report.get("outcomes", [])
    if not outs:
        return []

    def delta(o):
        return o.get("comparison", {}).get("abs_profit_change", 0) or 0
    best, worst = max(outs, key=delta), min(outs, key=delta)
    viable = sum(1 for o in outs if o.get("comparison", {}).get("viable"))
    txt = (f"Baseline expected profit <b>{_isk(base.get('expected_profit'))}</b> "
           f"(P(loss) {_pct(base.get('prob_loss'))}). Across <b>{len(outs)}</b> scenarios, "
           f"<b>{viable}</b> stay viable. Best case <b>{best.get('name')}</b> "
           f"({_signed_isk(delta(best))}); worst case <b>{worst.get('name')}</b> "
           f"({_signed_isk(delta(worst))}).")
    return [_h("Executive summary"), _p(txt), Spacer(1, 3 * mm)]


def _scenario_story(report: dict) -> list:
    base = report.get("baseline", {})
    n_scn = len(report.get("outcomes", []))
    story: list = [
        _h(f"Scenario Simulation — {report.get('label', '')}", 16),
        _p(f"Source: <b>{report.get('source', '—')}</b> · "
           f"Product: <b>{report.get('product_name', report.get('target_type_id', '—'))}</b> · "
           f"Engine: <b>{report.get('engine', '—')}</b> · "
           f"Scenarios: <b>{n_scn}</b>"),
        _p(f"Run at: {report.get('created_at', '—')}"),
        Spacer(1, 3 * mm),
    ]
    story += _share_block(report)
    story += _scn_exec(report)
    story += [_h("Baseline profit distribution")]
    chart = _profit_histogram(base)
    if chart is not None:
        story += [chart, Spacer(1, 2 * mm)]
    base_rows = [
        ["Baseline metric", "Value"],
        ["Expected profit  E[Profit]", _isk(base.get("expected_profit"))],
        ["Std deviation  σ", _isk(base.get("std"))],
        ["VaR 5% / VaR 1%", f"{_isk(base.get('var5'))}  /  {_isk(base.get('var1'))}"],
        ["CVaR 5% (expected shortfall)", _isk(base.get("cvar5"))],
        ["Probability of loss", _pct(base.get("prob_loss"))],
    ]
    story += [
        _table(base_rows, col_widths=[95 * mm, 75 * mm]),
        Spacer(1, 5 * mm),
        _h("Scenario comparison vs baseline"),
        _comparison_table(report),
        Spacer(1, 5 * mm),
    ]
    ranked = report.get("ranking") or []
    if ranked:
        story += [_h("Risk-adjusted strategy ranking"), _ranking_table(ranked), Spacer(1, 5 * mm)]
    tornado = _sensitivity_tornado(report)
    if tornado is not None:
        story += [_h("Sensitivity analysis"), tornado]
    return story


def render_scenario_pdf(report: dict) -> bytes:
    """One scenario analysis → PDF bytes. ``report`` keys: label, source,
    product_name, engine, created_at, params(dict), baseline(SimMetrics asdict),
    outcomes([ScenarioOutcome asdict]), ranking([{rank,label,score}])."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm,
                            leftMargin=15 * mm, rightMargin=15 * mm,
                            title=f"Scenario analysis — {report.get('label', '')}")
    doc.build(_scenario_story(report))
    return buf.getvalue()


# ── combined 'whole product' report ───────────────────────────────────────────

def render_product_pdf(product_name: str, sim_runs: list[dict],
                       scenario_analyses: list[dict], *, share_code: Optional[str] = None,
                       share_url: Optional[str] = None) -> bytes:
    """Everything for one product → one consolidated PDF: a header, then each
    Monte-Carlo run (``sim_runs`` are per-run report dicts as for
    ``sim_report_pdf.render_run_pdf``), then each scenario analysis
    (``scenario_analyses`` are report dicts as for ``render_scenario_pdf``)."""
    story: list = [
        _h(f"Product Report — {product_name}", 16),
        _p(f"{len(sim_runs)} Monte-Carlo run(s) · {len(scenario_analyses)} scenario analysis(es)."),
    ]
    story += _share_block({"share_code": share_code, "share_url": share_url})
    if sim_runs:
        cmp_rows = [["Monte-Carlo run", "E[Profit]", "σ", "VaR 5%", "P(loss)"]]
        for r in sim_runs:
            m = r.get("metrics", {})
            cmp_rows.append([r.get("label", "—"), _isk(m.get("expected_profit")),
                             _isk(m.get("std")), _isk(m.get("var5")), _pct(m.get("prob_loss"))])
        story += [Spacer(1, 3 * mm), _h("Monte-Carlo runs"), _table(cmp_rows)]
    for r in sim_runs:
        story.append(PageBreak())
        story += _run_story(r)
    for a in scenario_analyses:
        story.append(PageBreak())
        story += _scenario_story(a)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm,
                            leftMargin=15 * mm, rightMargin=15 * mm,
                            title=f"Product report — {product_name}")
    doc.build(story)
    return buf.getvalue()
