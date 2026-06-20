"""
PDF rendering for a single manufacturing **production** calculation (the Calculator
tab). The Monte-Carlo and Scenario tabs already produce PDFs; this is the detailed
report of the production job itself — the bill of materials (ME-adjusted quantities),
the job-cost breakdown (EIV / system cost index / SCC), production time and the
profit summary.

Pure over plain dicts (the ``CalcResult`` asdict + a small meta block) — no ORM /
FastAPI — so it is unit-testable and callable from the router. Reuses the branded
letterhead + formatting/table helpers from :mod:`app.services.sim_report_pdf`.
"""
from __future__ import annotations

import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer

from app.services.sim_report_pdf import (
    _h, _isk, _p, _share_block, _table,
)


# ── formatting ────────────────────────────────────────────────────────────────

def _qty(x) -> str:
    try:
        return f"{int(round(float(x))):,}"
    except (TypeError, ValueError):
        return "—"


def _pct1(x) -> str:
    return "—" if x is None else f"{float(x):.2f}%"


def _duration(seconds) -> str:
    """Seconds → ``Dd Hh Mm Ss`` (EVE-style), dropping leading zero units."""
    try:
        s = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "—"
    if s <= 0:
        return "0s"
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, sec = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h or d:
        parts.append(f"{h}h")
    if m or h or d:
        parts.append(f"{m}m")
    parts.append(f"{sec}s")
    return " ".join(parts)


# ── sections ──────────────────────────────────────────────────────────────────

def _summary_line(meta: dict) -> str:
    bits = [f"Runs <b>{_qty(meta.get('runs'))}</b>"]
    if (meta.get("windows") or 1) > 1:
        bits.append(f"Windows <b>{meta.get('windows')}</b>")
    bits.append(f"ME <b>{meta.get('me', 0)}</b> · TE <b>{meta.get('te', 0)}</b>")
    if meta.get("facility_name"):
        loc = meta["facility_name"]
        if meta.get("system_name"):
            loc += f" ({meta['system_name']})"
        bits.append(f"Facility <b>{loc}</b>")
    if meta.get("produce_character"):
        bits.append(f"Producer <b>{meta['produce_character']}</b>")
    if meta.get("sell_character"):
        bits.append(f"Seller <b>{meta['sell_character']}</b>")
    return " · ".join(bits)


def _exec_summary(result: dict) -> list:
    res = result.get("results", {})
    profit = float(res.get("profit") or 0.0)
    margin = float(res.get("margin_pct") or 0.0)
    sell = float(res.get("total_sell") or 0.0)
    verdict = "profitable" if profit > 0 else ("break-even" if profit == 0 else "loss-making")
    txt = (f"Net revenue <b>{_isk(sell)}</b> against total cost "
           f"<b>{_isk(res.get('total_costs'))}</b> → profit <b>{_isk(profit)}</b> "
           f"(margin <b>{margin:.1f}%</b>). Verdict: <b>{verdict}</b>.")
    return [_h("Production summary"), _p(txt), Spacer(1, 3 * mm)]


def _output_block(result: dict) -> list:
    o = result.get("output", {})
    rows = [
        ["Product", "Units", "Unit price", "Gross sell", "Net sell"],
        [o.get("name", "—"), _qty(o.get("quantity")), _isk(o.get("unit_price")),
         _isk(o.get("gross_sell")), _isk(o.get("net_sell"))],
    ]
    return [_h("Output"), _table(rows)]


def _materials_block(result: dict) -> list:
    mats = result.get("materials", []) or []
    rows = [["Material", "Base qty", "ME qty", "Saved", "Unit price", "Cost"]]
    for m in mats:
        rows.append([
            m.get("name", "—"), _qty(m.get("base_qty")), _qty(m.get("adj_qty")),
            _qty(m.get("saved")), _isk(m.get("unit_cost")), _isk(m.get("gross_cost")),
        ])
    rows.append(["Total materials", "", "", "", "", _isk(result.get("materials_total_gross"))])
    return [_h("Bill of materials"),
            _table(rows, col_widths=[60 * mm, 22 * mm, 22 * mm, 18 * mm, 24 * mm, 24 * mm])]


def _job_cost_block(result: dict) -> list:
    jc = result.get("job_cost", {})
    rows = [
        ["Job cost component", "Value"],
        ["Estimated item value (EIV)", _isk(jc.get("estimated_item_value"))],
        ["System cost index", _pct1(jc.get("system_cost_index_pct"))],
        ["System cost", _isk(jc.get("system_cost"))],
        ["Structure / rig bonus", "− " + _isk(jc.get("structure_bonus"))],
        ["Gross install cost", _isk(jc.get("gross_install_cost"))],
        ["Facility tax", _isk(jc.get("facility_tax"))],
        ["SCC surcharge", _isk(jc.get("scc_surcharge"))],
        ["Net install cost", _isk(jc.get("net_install_cost"))],
    ]
    return [_h("Job installation cost"), _table(rows, col_widths=[95 * mm, 75 * mm])]


def _metrics_block(result: dict) -> list:
    jt = result.get("job_time", {})
    o = result.get("output", {})
    rows = [
        ["Production metric", "Value"],
        ["Time per job", _duration(jt.get("seconds"))],
        ["Job time (hours)", f"{float(jt.get('hours') or 0):.2f} h"],
        ["Parallel windows", _qty(result.get("windows"))],
        ["Runs per window", _qty(result.get("runs_per_window"))],
        ["Total slot-hours", f"{float(jt.get('total_slot_hours') or 0):.2f} h"],
        ["Units produced", _qty(o.get("quantity"))],
    ]
    return [_h("Production metrics"), _table(rows, col_widths=[95 * mm, 75 * mm])]


def _results_block(result: dict) -> list:
    res = result.get("results", {})
    rows = [
        ["Result", "Value"],
        ["Total material cost", _isk(res.get("total_material_cost"))],
        ["Install cost", _isk(res.get("total_install_cost"))],
        ["Blueprint (BPC) cost", _isk(result.get("bpc_cost"))],
        ["Total production cost", _isk(res.get("total_costs"))],
        ["Net sell revenue", _isk(res.get("total_sell"))],
        ["Profit", _isk(res.get("profit"))],
        ["Margin", _pct1(res.get("margin_pct"))],
    ]
    return [_h("Profit & loss"), _table(rows, col_widths=[95 * mm, 75 * mm])]


def render_production_pdf(report: dict) -> bytes:
    """One production calculation → PDF bytes. ``report`` keys:
    ``meta`` (product_name, runs, windows, me, te, facility_name, system_name,
    produce_character, sell_character, created_at), ``result`` (CalcResult asdict),
    and optionally ``share_code`` / ``share_url`` for the branded letterhead/QR."""
    meta = report.get("meta", {}) or {}
    result = report.get("result", {}) or {}
    product_name = meta.get("product_name") or result.get("output", {}).get("name", "—")

    story: list = [
        _h(f"Manufacturing Production Report — {product_name}", 16),
        _p(_summary_line(meta)),
    ]
    if meta.get("created_at"):
        story.append(_p(f"Generated: {meta['created_at']}"))
    story.append(Spacer(1, 3 * mm))
    story += _share_block(report)
    story += _exec_summary(result)
    story += _output_block(result)
    story += [Spacer(1, 4 * mm)]
    story += _materials_block(result)
    story += [Spacer(1, 4 * mm)]
    story += _job_cost_block(result)
    story += [Spacer(1, 4 * mm)]
    story += _metrics_block(result)
    story += [Spacer(1, 4 * mm)]
    story += _results_block(result)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            title=f"Production — {product_name}")
    doc.build(story)
    return buf.getvalue()
