"""
PDF rendering for Monte-Carlo profit-simulation reports.

Pure over plain dicts (a stored SimulationRun's metrics + params) — no ORM/FastAPI,
so it is unit-testable and callable by both the API and any batch job. Uses
ReportLab (pure-python; charts via reportlab.graphics, no matplotlib → the Docker
image stays slim).

Two documents, per the IO-22 spec:
* ``render_run_pdf`` — one simulation run (inputs, risk metrics, profit
  distribution, percentiles, cost breakdown, completion-time stats);
* ``render_rollup_pdf`` — a project roll-up comparing every run with the ranking.
"""
from __future__ import annotations

import io
from typing import Optional

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

_styles = getSampleStyleSheet()
_HEAD = colors.HexColor("#1f3a5f")
_GRID = colors.HexColor("#b0b8c4")
_ALT = colors.HexColor("#eef2f7")


# ── formatting ────────────────────────────────────────────────────────────────

def _isk(x: Optional[float]) -> str:
    if x is None:
        return "—"
    a = abs(x)
    if a >= 1e9:
        return f"{x / 1e9:,.2f} B"
    if a >= 1e6:
        return f"{x / 1e6:,.2f} M"
    if a >= 1e3:
        return f"{x / 1e3:,.2f} K"
    return f"{x:,.2f}"


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x * 100:.2f}%"


def _num(x: Optional[float], nd: int = 3) -> str:
    return "—" if x is None else f"{x:.{nd}f}"


def _table(rows: list[list], col_widths=None, header: bool = True) -> Table:
    t = Table(rows, colWidths=col_widths, hAlign="LEFT")
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, _ALT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), _HEAD),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    t.setStyle(TableStyle(style))
    return t


def _h(text: str, size: int = 13):
    s = _styles["Heading2"].clone("h")
    s.textColor = _HEAD
    s.fontSize = size
    return Paragraph(text, s)


def _p(text: str):
    return Paragraph(text, _styles["BodyText"])


def _profit_histogram(metrics: dict, width=170 * mm, height=58 * mm) -> Optional[Drawing]:
    counts = metrics.get("hist_counts") or []
    edges = metrics.get("hist_edges") or []
    if len(counts) < 2 or len(edges) != len(counts) + 1:
        return None
    d = Drawing(width, height)
    chart = VerticalBarChart()
    chart.x, chart.y = 14 * mm, 12 * mm
    chart.width, chart.height = width - 22 * mm, height - 20 * mm
    chart.data = [counts]
    chart.bars[0].fillColor = _HEAD
    chart.bars[0].strokeColor = None
    chart.valueAxis.valueMin = 0
    chart.categoryAxis.visibleTicks = 0
    # label a handful of bin edges along the x-axis
    step = max(1, len(counts) // 6)
    chart.categoryAxis.categoryNames = [
        _isk((edges[i] + edges[i + 1]) / 2) if i % step == 0 else "" for i in range(len(counts))
    ]
    chart.categoryAxis.labels.angle = 30
    chart.categoryAxis.labels.fontSize = 6
    chart.categoryAxis.labels.dy = -4
    chart.valueAxis.labels.fontSize = 6
    d.add(chart)
    return d


# ── per-run report ──────────────────────────────────────────────────────────────

def _metrics_block(m: dict) -> list:
    pcts = m.get("percentiles", {})
    risk_rows = [
        ["Metric", "Value"],
        ["Expected profit  E[Profit]", _isk(m.get("expected_profit"))],
        ["Median profit", _isk(m.get("median_profit"))],
        ["Std deviation  σ", _isk(m.get("std"))],
        ["Coefficient of variation", _num(m.get("cv"))],
        ["VaR 5%", _isk(m.get("var5"))],
        ["VaR 1%", _isk(m.get("var1"))],
        ["CVaR 5% (expected shortfall)", _isk(m.get("cvar5"))],
        ["Worst 1% (mean)", _isk(m.get("worst1"))],
        ["Probability of loss", _pct(m.get("prob_loss"))],
        ["Sharpe-like (E/σ)", _num(m.get("sharpe_like"))],
        ["Risk-adjusted (E − λσ)", _isk(m.get("risk_adjusted"))],
        ["Best / worst", f"{_isk(m.get('best'))}  /  {_isk(m.get('worst'))}"],
    ]
    pct_rows = [
        ["Percentile", "p1", "p5", "p25", "p50", "p75", "p95", "p99"],
        ["Profit"] + [_isk(pcts.get(k)) for k in ("p1", "p5", "p25", "p50", "p75", "p95", "p99")],
    ]
    return [
        _h("Risk metrics"),
        _table(risk_rows, col_widths=[95 * mm, 75 * mm]),
        Spacer(1, 5 * mm),
        _h("Outcome percentiles"),
        _table(pct_rows),
    ]


def _breakdown_block(m: dict) -> list:
    bd = m.get("breakdown", {})
    rows = [["Component", "Mean", "p5", "p50", "p95"]]
    for key, label in [("revenue", "Sales revenue"), ("material_cost", "Material cost"),
                       ("taxes_fees", "Taxes & fees"), ("logistics", "Logistics")]:
        c = bd.get(key, {})
        rows.append([label, _isk(c.get("mean")), _isk(c.get("p5")), _isk(c.get("p50")), _isk(c.get("p95"))])
    time_rows = [
        ["Completion time", "Value"],
        ["Mean", f"{_num(m.get('time_mean_h'), 2)} h"],
        ["Median", f"{_num(m.get('time_median_h'), 2)} h"],
        ["95th percentile", f"{_num(m.get('time_p95_h'), 2)} h"],
        ["Per production slot/job", f"{_num(m.get('time_per_job_h'), 2)} h"],
    ]
    return [
        _h("Per-scenario cost breakdown"),
        _table(rows),
        Spacer(1, 5 * mm),
        _h("Operational metrics"),
        _table(time_rows, col_widths=[95 * mm, 75 * mm]),
    ]


def _run_story(report: dict) -> list:
    m = report.get("metrics", {})
    params = report.get("params", {})
    n_iter = m.get("n_iterations") or params.get("n_iterations")
    n_iter_str = f"{n_iter:,}" if isinstance(n_iter, int) else "—"
    story: list = [
        _h(f"Monte-Carlo Profit Simulation — {report.get('label', '')}", 16),
        _p(f"Source: <b>{report.get('source', '—')}</b> · "
           f"Product: <b>{report.get('product_name', report.get('target_type_id', '—'))}</b> · "
           f"Engine: <b>{report.get('engine', '—')}</b> · "
           f"Iterations: <b>{n_iter_str}</b>"),
        _p(f"Run at: {report.get('created_at', '—')}"),
        Spacer(1, 3 * mm),
    ]
    chart = _profit_histogram(m)
    if chart is not None:
        story += [_h("Profit distribution"), chart, Spacer(1, 3 * mm)]
    story += _metrics_block(m)
    story += [Spacer(1, 5 * mm)]
    story += _breakdown_block(m)
    return story


def render_run_pdf(report: dict) -> bytes:
    """One simulation run → PDF bytes. ``report`` keys: label, source,
    product_name, engine, created_at, params(dict), metrics(SimMetrics asdict)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            title=f"Simulation — {report.get('label', '')}")
    doc.build(_run_story(report))
    return buf.getvalue()


# ── project roll-up ───────────────────────────────────────────────────────────

def render_rollup_pdf(project_name: str, runs: list[dict],
                      ranked: Optional[list[dict]] = None) -> bytes:
    """All runs in a project → one consolidated PDF: a comparison table, the
    strategy ranking, then each run's full page. ``runs`` are per-run report dicts
    (same shape as ``render_run_pdf``); ``ranked`` is the risk-engine output
    ``[{rank,label,score}]``."""
    story: list = [
        _h(f"Profit Simulation Roll-up — {project_name}", 16),
        _p(f"{len(runs)} simulation run(s)."),
        Spacer(1, 4 * mm),
        _h("Strategy comparison"),
    ]
    cmp_rows = [["Strategy", "E[Profit]", "σ", "VaR 5%", "P(loss)", "Sharpe", "Ret/slot"]]
    for r in runs:
        m = r.get("metrics", {})
        cmp_rows.append([
            r.get("label", "—"), _isk(m.get("expected_profit")), _isk(m.get("std")),
            _isk(m.get("var5")), _pct(m.get("prob_loss")), _num(m.get("sharpe_like")),
            _isk(m.get("return_per_slot")),
        ])
    story.append(_table(cmp_rows))

    if ranked:
        story += [Spacer(1, 5 * mm), _h("Risk-adjusted ranking")]
        rank_rows = [["Rank", "Strategy", "Composite score"]]
        for r in ranked:
            rank_rows.append([str(r.get("rank")), r.get("label", "—"), _num(r.get("score"))])
        story.append(_table(rank_rows, col_widths=[20 * mm, 110 * mm, 40 * mm]))

    for r in runs:
        story.append(PageBreak())
        story += _run_story(r)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            title=f"Roll-up — {project_name}")
    doc.build(story)
    return buf.getvalue()
