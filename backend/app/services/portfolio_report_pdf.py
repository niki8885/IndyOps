"""
PDF rendering for a trade-haul **portfolio** report (Market → Jita - C-J → Auto
scanner → Optimize). Mirrors :mod:`app.services.production_report_pdf`: pure over
plain dicts (the optimizer result + a small meta block), reusing the branded
letterhead + table/format helpers from :mod:`app.services.sim_report_pdf`.

The report answers "what and how much to buy to fit a target ISK budget": the
trading character's taxes/fees, the Markowitz allocation per item, and the
portfolio totals (capital, expected profit, ROI, σ, cargo m³).
"""
from __future__ import annotations

import io
from typing import Optional

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer

from app.services.sim_report_pdf import _GRID, _HEAD, _h, _isk, _p, _share_block, _table

_ASSET_DOT = colors.HexColor("#8a93a3")
_CHOSEN = colors.HexColor("#1e9e5a")

# best_method key → short label for the table (full labels live in services.trade)
_METHOD_LABEL = {
    "sell_buy": "Sell→Buy", "sell_sell": "Sell→Sell",
    "buy_buy": "Buy→Buy", "buy_sell": "Buy→Sell",
}


def _qty(x) -> str:
    try:
        return f"{int(round(float(x))):,}"
    except (TypeError, ValueError):
        return "—"


def _pct(x, nd: int = 1) -> str:
    return "—" if x is None else f"{float(x) * 100:.{nd}f}%"


def _summary_line(meta: dict) -> str:
    bits = ["Route <b>Jita → C-J6MT</b>", f"Budget <b>{_isk(meta.get('budget'))}</b>"]
    if meta.get("character_name"):
        bits.append(f"Trader <b>{meta['character_name']}</b>")
    bits.append(f"Sales tax <b>{meta.get('sales_tax_pct', 0):.2f}%</b> · "
                f"Broker <b>{meta.get('broker_fee_pct', 0):.2f}%</b>")
    bits.append(f"Courier <b>{_isk(meta.get('courier_per_m3'))}/m³</b>")
    bits.append(f"Risk λ <b>{meta.get('risk_aversion', 0):g}</b>")
    if meta.get("engine"):
        bits.append(f"Engine <b>{meta['engine']}</b>")
    return " · ".join(bits)


def _totals_block(totals: dict) -> list:
    rows = [
        ["Portfolio metric", "Value"],
        ["Budget", _isk(totals.get("budget"))],
        ["Capital deployed", _isk(totals.get("capital_used"))],
        ["Leftover (unspent)", _isk(totals.get("leftover"))],
        ["Expected profit", _isk(totals.get("expected_profit"))],
        ["Expected ROI", _pct(totals.get("portfolio_roi"))],
        ["Portfolio σ (return)", f"{float(totals.get('stddev') or 0.0) * 100:.2f}%"],
        ["Total cargo", f"{float(totals.get('total_volume_m3') or 0.0):,.1f} m³"],
        ["Items bought", f"{totals.get('n_assets', 0)} / {totals.get('n_considered', 0)}"],
    ]
    return [_h("Portfolio summary"), _table(rows, col_widths=[95 * mm, 75 * mm])]


def _allocation_block(allocs: list[dict]) -> list:
    rows = [["Item", "Method", "Qty", "Unit cost", "Capital", "Exp. profit", "ROI", "Wt%", "m³"]]
    for a in allocs:
        if not a.get("qty"):
            continue
        rows.append([
            a.get("name", "—"), _METHOD_LABEL.get(a.get("best_method"), a.get("best_method") or "—"),
            _qty(a.get("qty")), _isk(a.get("unit_cost")), _isk(a.get("capital")),
            _isk(a.get("expected_profit")), _pct(a.get("roi")),
            f"{float(a.get('weight') or 0.0) * 100:.1f}", f"{float(a.get('volume_m3') or 0.0):,.1f}",
        ])
    if len(rows) == 1:
        rows.append(["—", "", "", "", "", "", "", "", ""])
    return [_h("Allocation"),
            _table(rows, col_widths=[44 * mm, 18 * mm, 16 * mm, 20 * mm, 22 * mm,
                                     22 * mm, 14 * mm, 12 * mm, 14 * mm])]


def _frontier_chart(frontier: dict, width=152 * mm, height=72 * mm) -> Optional[Drawing]:
    """Markowitz efficient frontier: optimal risk/return curve (line) with each item
    scattered and the chosen portfolio marked (◆). Axes in % (σ vs expected ROI)."""
    pts = frontier.get("points") or []
    if len(pts) < 2:
        return None
    line = [(p["stddev"] * 100, p["exp_return"] * 100) for p in pts]
    assets = [(a["stddev"] * 100, a["exp_return"] * 100) for a in (frontier.get("assets") or [])] or [line[0]]
    ch = frontier.get("chosen") or {}
    chosen = [((ch.get("stddev") or 0.0) * 100, (ch.get("exp_return") or 0.0) * 100)]

    d = Drawing(width, height)
    lp = LinePlot()
    lp.x, lp.y = 15 * mm, 12 * mm
    lp.width, lp.height = width - 22 * mm, height - 20 * mm
    lp.data = [line, assets, chosen]
    lp.lines[0].strokeColor = _HEAD
    lp.lines[0].strokeWidth = 1.4
    lp.lines[1].strokeColor = None
    m_asset = makeMarker("FilledCircle"); m_asset.size = 3; m_asset.fillColor = _ASSET_DOT
    lp.lines[1].symbol = m_asset
    lp.lines[2].strokeColor = None
    m_chosen = makeMarker("FilledDiamond"); m_chosen.size = 8; m_chosen.fillColor = _CHOSEN
    lp.lines[2].symbol = m_chosen
    for ax in (lp.xValueAxis, lp.yValueAxis):
        ax.labels.fontSize = 6
        ax.labelTextFormat = "%0.1f"
        ax.strokeColor = _GRID
    d.add(lp)
    d.add(String(width / 2, 2, "risk σ (%)", fontSize=6, fillColor=_GRID, textAnchor="middle"))
    d.add(String(3, height - 6, "exp. ROI (%)", fontSize=6, fillColor=_GRID))
    return d


def _weights_chart(allocs: list[dict], width=152 * mm, height=56 * mm) -> Optional[Drawing]:
    """Per-item portfolio weight (%) as a bar chart (top 12 bought items)."""
    rows = [(a.get("name", "—"), float(a.get("weight") or 0.0) * 100) for a in allocs if a.get("qty")][:12]
    if not rows:
        return None
    d = Drawing(width, height)
    bc = VerticalBarChart()
    bc.x, bc.y = 14 * mm, 16 * mm
    bc.width, bc.height = width - 20 * mm, height - 24 * mm
    bc.data = [[v for _, v in rows]]
    bc.bars[0].fillColor = _HEAD
    bc.bars[0].strokeColor = None
    bc.valueAxis.valueMin = 0
    bc.valueAxis.labels.fontSize = 6
    bc.categoryAxis.categoryNames = [n[:16] for n, _ in rows]
    bc.categoryAxis.labels.angle = 30
    bc.categoryAxis.labels.fontSize = 6
    bc.categoryAxis.labels.dy = -5
    bc.categoryAxis.visibleTicks = 0
    d.add(bc)
    return d


def render_portfolio_pdf(report: dict) -> bytes:
    """One optimized haul portfolio → PDF bytes. ``report`` keys: ``meta``
    (character_name, sales_tax_pct, broker_fee_pct, courier_per_m3, budget,
    risk_aversion, engine, created_at), ``result`` (``{allocations, totals}`` from
    :func:`services.portfolio.build_portfolio`, with ``totals.stddev`` added), and
    optionally ``share_code`` / ``share_url`` for the branded letterhead/QR."""
    meta = report.get("meta", {}) or {}
    result = report.get("result", {}) or {}
    allocs = result.get("allocations", []) or []
    totals = result.get("totals", {}) or {}

    story: list = [
        _h("Trade Portfolio Report — Jita → C-J6MT", 16),
        _p(_summary_line(meta)),
    ]
    if meta.get("created_at"):
        story.append(_p(f"Generated: {meta['created_at']}"))
    story.append(Spacer(1, 3 * mm))
    story += _share_block(report)
    story += _totals_block(totals)

    frontier = _frontier_chart(result.get("frontier") or {})
    if frontier is not None:
        story += [Spacer(1, 4 * mm), _h("Efficient frontier"),
                  _p("Optimal risk/return curve. Grey dots = individual items, "
                     "<font color='#1e9e5a'>◆</font> = chosen portfolio."),
                  frontier]

    story += [Spacer(1, 4 * mm)]
    story += _allocation_block(allocs)

    weights = _weights_chart(allocs)
    if weights is not None:
        story += [Spacer(1, 4 * mm), _h("Allocation weights"), weights]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            title="Trade Portfolio — Jita → C-J6MT")
    doc.build(story)
    return buf.getvalue()
