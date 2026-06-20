"""PDF rendering for the Calculator production report (bill of materials, job-cost
breakdown, time, P&L). Pure — no DB/web."""
from dataclasses import asdict

from app.services.manufacturing import CalcInput, Material, run_calculation
from app.services import production_report_pdf as pdf


def _result(**kw):
    base = dict(
        product_name="Caracal", product_qty_per_run=1, runs=10, me=10, te=20,
        base_time_per_run=600,
        materials=[Material(34, "Tritanium", 1000, 5.0), Material(35, "Pyerite", 400, 10.0)],
        output_price=2_000_000.0, bpc_cost=50_000.0, broker_fee_pct=3.0,
        system_cost_index=0.05, facility_tax_pct=1.0, estimated_item_value=1_000_000.0,
    )
    base.update(kw)
    return asdict(run_calculation(CalcInput(**base)))


def test_render_production_pdf_is_valid():
    result = _result()
    out = pdf.render_production_pdf({
        "meta": {"product_name": "Caracal", "runs": 10, "windows": 1, "me": 10, "te": 20,
                 "facility_name": "GPLB-C Sotiyo", "system_name": "GPLB-C",
                 "produce_character": "Azimo Thyui", "created_at": "2026-06-20 12:00:00"},
        "result": result,
        "share_code": "12345678",
    })
    assert out[:4] == b"%PDF" and len(out) > 2000


def test_render_production_pdf_without_share_code_or_meta():
    out = pdf.render_production_pdf({"result": _result()})
    assert out[:4] == b"%PDF"


def test_render_production_pdf_tolerates_empty_result():
    out = pdf.render_production_pdf({"meta": {}, "result": {}})
    assert out[:4] == b"%PDF"


def test_duration_formatting():
    assert pdf._duration(0) == "0s"
    assert pdf._duration(90) == "1m 30s"
    assert pdf._duration(3661) == "1h 1m 1s"
    assert pdf._duration(90061) == "1d 1h 1m 1s"
    assert pdf._duration(None) == "—"
