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

import hashlib
import io
from pathlib import Path
from typing import Optional

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib.utils import ImageReader
from reportlab.platypus import HRFlowable, Image

from app.services import barcodes

_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"
_BRAND = "IndyOps"
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


def _exec_summary(m: dict) -> list:
    """A plain-language headline so the report opens with the verdict, not a table."""
    ep = float(m.get("expected_profit") or 0.0)
    rev = float((m.get("breakdown", {}).get("revenue", {}) or {}).get("mean") or 0.0)
    margin = (ep / rev * 100.0) if rev else 0.0
    ploss = float(m.get("prob_loss") or 0.0)
    verdict = "profitable" if (ep > 0 and ploss < 0.25) else ("speculative" if ep > 0 else "loss-making")
    txt = (f"Expected profit <b>{_isk(ep)}</b> on mean revenue {_isk(rev)} "
           f"(margin <b>{margin:.1f}%</b>). Probability of loss <b>{_pct(ploss)}</b>; "
           f"VaR 5% {_isk(m.get('var5'))}, CVaR 5% {_isk(m.get('cvar5'))}; "
           f"risk-adjusted (E−λσ) {_isk(m.get('risk_adjusted'))}. "
           f"Worst observed {_isk(m.get('worst'))}, best {_isk(m.get('best'))}. "
           f"Verdict: <b>{verdict}</b>.")
    return [_h("Executive summary"), _p(txt), Spacer(1, 3 * mm)]


def _breakdown_chart(m: dict, width=120 * mm, height=46 * mm) -> Optional[Drawing]:
    """Mean revenue vs cost components as a small bar chart."""
    bd = m.get("breakdown", {})
    keys = [("revenue", "Revenue"), ("material_cost", "Material"),
            ("taxes_fees", "Taxes"), ("logistics", "Logistics")]
    vals = [float((bd.get(k, {}) or {}).get("mean", 0.0) or 0.0) for k, _ in keys]
    if not any(vals):
        return None
    d = Drawing(width, height)
    chart = VerticalBarChart()
    chart.x, chart.y = 16 * mm, 8 * mm
    chart.width, chart.height = width - 22 * mm, height - 16 * mm
    chart.data = [vals]
    chart.bars[0].fillColor = _HEAD
    chart.bars[0].strokeColor = None
    chart.valueAxis.valueMin = 0
    chart.categoryAxis.categoryNames = [lbl for _, lbl in keys]
    chart.categoryAxis.labels.fontSize = 7
    chart.valueAxis.labels.fontSize = 6
    d.add(chart)
    return d


def job_ref(code: str) -> str:
    """Short human reference for a (long, self-contained) share code."""
    return hashlib.sha1((code or "").encode("utf-8")).hexdigest()[:8].upper()


def _logo_image(height=13 * mm) -> Optional[Image]:
    try:
        if _LOGO_PATH.is_file():
            iw, ih = ImageReader(str(_LOGO_PATH)).getSize()
            return Image(str(_LOGO_PATH), width=height * iw / max(1, ih), height=height)
    except Exception:  # pragma: no cover - defensive
        return None
    return None


def _brand_para():
    s = _styles["Heading1"].clone("brand")
    s.textColor = _HEAD
    s.fontSize = 18
    s.spaceAfter = 0
    return Paragraph(f"{_BRAND} <font size=10 color='#5a6b82'>· Industry Toolkit</font>", s)


def _share_block(report: dict) -> list:
    """Branded letterhead at the very top of every document: app logo + name on the left,
    the share-code Code128 barcode (large) on the right, a separator, then the QR + the
    'print &amp; keep' note. The QR/barcode reopen the build (server-stored, ~1 week TTL)."""
    code = report.get("share_code")
    code = str(code) if code else ""
    url = report.get("share_url") or code

    # ── header: logo + name (left), large barcode (right) ──
    logo = _logo_image()
    name = _brand_para()
    if logo is not None:
        left = Table([[logo, name]], colWidths=[18 * mm, None], hAlign="LEFT")
        left.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    else:
        left = name
    right = ""
    if code:
        try:
            right = barcodes.code128_drawing(code, bar_height=15 * mm, bar_width=1.1)
        except Exception:  # pragma: no cover - defensive
            right = _p(f"Code {code}")
    header = Table([[left, right]], colWidths=[108 * mm, 62 * mm], hAlign="LEFT")
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    out: list = [header, HRFlowable(width="100%", thickness=1.2, color=_HEAD,
                                    spaceBefore=3 * mm, spaceAfter=3 * mm)]
    if not code:
        return out

    # ── after the separator: QR + the reopen / keep-a-printout note ──
    try:
        qrd = barcodes.qr_drawing(url, 32 * mm)
        note = _p(
            f"<b>Shareable job code {code}</b><br/>Scan the QR or enter the code in the "
            f"{_BRAND} calculator to reopen this build with the same parameters. Valid ~1 week."
            f"<br/><i>Tip: for a permanent record, print this page and keep it — the code "
            f"expires, so don't rely on it alone.</i>")
        qrow = Table([[qrd, note]], colWidths=[36 * mm, 134 * mm], hAlign="LEFT")
        qrow.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        out += [qrow, Spacer(1, 4 * mm)]
    except Exception:  # pragma: no cover - defensive
        out += [_p(f"Code <b>{code}</b>"), Spacer(1, 3 * mm)]
    return out


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
    block = [_h("Per-scenario cost breakdown"), _table(rows)]
    bchart = _breakdown_chart(m)
    if bchart is not None:
        block += [Spacer(1, 2 * mm), bchart]
    block += [
        Spacer(1, 5 * mm),
        _h("Operational metrics"),
        _table(time_rows, col_widths=[95 * mm, 75 * mm]),
    ]
    return block


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
    story += _share_block(report)
    story += _exec_summary(m)
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
