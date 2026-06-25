"""Unit tests for the manufacturing FIFO cost ledger (pure, no DB/network)."""
import datetime

from app.services import industry_ledger


def _buy(tid, qty, unit_cost, day):
    return {"kind": "buy", "date": datetime.datetime(2026, 6, day, 10, 0, 0),
            "type_id": tid, "qty": qty, "unit_cost": unit_cost}


def _build(job_id, day, inputs, product_type_id, product_qty, runs, job_cost, **kw):
    return {"kind": "build", "date": datetime.datetime(2026, 6, day, 12, 0, 0),
            "completed_at": f"2026-06-{day:02d}T12:00:00", "job_id": job_id,
            "owner": "Trader", "blueprint_name": "BP", "product_type_id": product_type_id,
            "product_name": f"P{product_type_id}", "runs": runs, "product_qty": product_qty,
            "job_cost": job_cost, "copy_cost": kw.get("copy_cost", 0.0), "inputs": inputs,
            "activity": kw.get("activity", "Manufacturing"), "produces": kw.get("produces", True),
            "custom_unit_price": kw.get("custom_unit_price")}


def _sell(tid, qty, price, day, broker_pct=0.0, tax_pct=0.0):
    return {"kind": "sell", "date": datetime.datetime(2026, 6, day, 14, 0, 0),
            "type_id": tid, "qty": qty, "unit_price": price, "name": f"P{tid}",
            "broker_pct": broker_pct, "tax_pct": tax_pct}


def _contract(contract_id, day, items, price, broker=0.0):
    return {"kind": "contract_sell", "date": datetime.datetime(2026, 6, day, 15, 0, 0),
            "contract_id": contract_id, "character": "Trader", "acceptor": "Buyer",
            "title": "Sale", "note": None, "price": price, "broker": broker, "items": items}


# ── run_ledger ─────────────────────────────────────────────────────────────────

def test_build_then_sell_realizes_profit():
    out = industry_ledger.run_ledger([
        _buy(34, 1000, 5.0, 1),
        _build(1, 2, [{"type_id": 34, "qty": 1000}], 9999, 10, 10, 1000.0),
        _sell(9999, 10, 1000.0, 3),
    ])
    j = out["jobs"][0]
    assert j["materials_cost"] == 5000.0 and j["unit_cost"] == 600.0   # (5000+1000)/10
    assert j["produced"] == 10 and j["sold"] == 10 and j["consumed"] == 0
    assert j["missing"] is False
    r = out["manufacturing"][0]
    assert r["units"] == 10 and r["total_build"] == 6000.0 and r["total_sell"] == 10000.0
    assert r["profit"] == 4000.0 and r["unit_build"] == 600.0


def test_missing_inputs_flag_excludes_profit():
    out = industry_ledger.run_ledger([
        _build(1, 1, [{"type_id": 34, "qty": 1000}], 9999, 10, 10, 1000.0),   # no buys → missing
        _sell(9999, 10, 1000.0, 2),
    ])
    j = out["jobs"][0]
    assert j["missing"] is True and j["materials_cost"] == 0.0
    assert j["sold"] == 10                       # sold is still counted
    assert out["manufacturing"] == []            # but profit is not


def test_consumed_tracks_intermediate_used_by_later_job():
    out = industry_ledger.run_ledger([
        _buy(34, 100, 1.0, 1),
        _build(1, 2, [{"type_id": 34, "qty": 100}], 5000, 5, 5, 0.0),    # → 5 components @20
        _build(2, 3, [{"type_id": 5000, "qty": 5}], 6000, 1, 1, 0.0),    # consumes the 5 components
    ])
    by_id = {j["job_id"]: j for j in out["jobs"]}
    assert by_id[1]["consumed"] == 5 and by_id[1]["sold"] == 0
    assert by_id[2]["materials_cost"] == 100.0 and by_id[2]["missing"] is False


def test_sell_fees_reduce_profit():
    out = industry_ledger.run_ledger([
        _buy(34, 1000, 5.0, 1),
        _build(1, 2, [{"type_id": 34, "qty": 1000}], 9999, 10, 10, 1000.0),
        _sell(9999, 10, 1000.0, 3, broker_pct=3.0, tax_pct=7.5),
    ])
    r = out["manufacturing"][0]
    # 10000 sell - 6000 build - 300 broker - 750 tax = 2950
    assert r["broker_sell"] == 300.0 and r["sales_tax"] == 750.0 and r["profit"] == 2950.0


def test_partial_material_shortfall_flags_missing():
    # only 600 of the 1000 needed are tracked → job flagged missing
    out = industry_ledger.run_ledger([
        _buy(34, 600, 5.0, 1),
        _build(1, 2, [{"type_id": 34, "qty": 1000}], 9999, 10, 10, 0.0),
    ])
    j = out["jobs"][0]
    assert j["missing"] is True and j["materials_cost"] == 3000.0   # 600 × 5


# ── non-producing activities + custom unit price ───────────────────────────────

def test_non_producing_activity_makes_no_sellable_lot():
    out = industry_ledger.run_ledger([
        _buy(34, 1000, 5.0, 1),
        _build(1, 2, [{"type_id": 34, "qty": 1000}], 9999, 10, 10, 1000.0, activity="Copying", produces=False),
        _sell(9999, 10, 1000.0, 3),
    ])
    assert out["manufacturing"] == []                 # no lot → nothing to realize
    j = out["jobs"][0]
    assert j["activity"] == "Copying" and j["materials_cost"] == 5000.0   # still costed


def test_custom_unit_price_overrides_and_clears_missing():
    out = industry_ledger.run_ledger([
        _build(1, 1, [{"type_id": 34, "qty": 1000}], 9999, 10, 10, 1000.0, custom_unit_price=50.0),
        _sell(9999, 10, 80.0, 2),
    ])
    j = out["jobs"][0]
    assert j["missing"] is False and j["unit_cost"] == 50.0 and j["custom_unit_price"] == 50.0
    r = out["manufacturing"][0]
    assert r["unit_build"] == 50.0 and r["total_build"] == 500.0 and r["profit"] == 300.0   # 800-500


def test_runs_missing_set_when_inputs_untracked():
    out = industry_ledger.run_ledger([
        _build(1, 1, [{"type_id": 34, "qty": 1000}], 9999, 10, 10, 1000.0),
    ])
    assert out["jobs"][0]["runs_missing"] == 10 and out["jobs"][0]["missing"] is True


# ── contract sales ─────────────────────────────────────────────────────────────

def test_contract_sell_realizes_profit_from_cost_basis():
    out = industry_ledger.run_ledger([
        _buy(34, 1000, 5.0, 1),
        _contract(77, 2, [{"type_id": 34, "qty": 1000}], 8000.0, broker=240.0),
    ])
    c = out["contracts"][0]
    assert c["total_cost"] == 5000.0 and c["total_sell"] == 8000.0
    assert c["broker_sell"] == 240.0 and c["sales_tax"] == 0.0
    assert c["profit"] == 2760.0 and c["missing"] is False   # 8000 - 5000 - 240


def test_contract_sell_flags_partial_cost_basis():
    out = industry_ledger.run_ledger([
        _buy(34, 600, 5.0, 1),
        _contract(77, 2, [{"type_id": 34, "qty": 1000}], 8000.0),
    ])
    c = out["contracts"][0]
    assert c["missing"] is True and c["total_cost"] == 3000.0   # only 600 tracked


def test_contract_sell_consumes_built_lots_and_bumps_sold():
    out = industry_ledger.run_ledger([
        _buy(34, 1000, 5.0, 1),
        _build(1, 2, [{"type_id": 34, "qty": 1000}], 9999, 10, 10, 1000.0),   # 10 widgets @600
        _contract(77, 3, [{"type_id": 9999, "qty": 10}], 10000.0),
    ])
    assert out["jobs"][0]["sold"] == 10
    c = out["contracts"][0]
    assert c["total_cost"] == 6000.0 and c["profit"] == 4000.0


# ── summaries ──────────────────────────────────────────────────────────────────

def test_summaries_totals_and_series():
    out = industry_ledger.run_ledger([
        _buy(34, 1000, 5.0, 1),
        _build(1, 2, [{"type_id": 34, "qty": 1000}], 9999, 10, 10, 1000.0),
        _sell(9999, 10, 1000.0, 3),
    ])
    ms = industry_ledger.summarize_manufacturing(out["manufacturing"])
    assert ms["total_profit"] == 4000.0 and ms["units"] == 10 and ms["trade_count"] == 1
    assert [x["date"] for x in ms["series"]] == ["2026-06-03"]
    js = industry_ledger.summarize_jobs(out["jobs"])
    assert js["job_count"] == 1 and js["total_job_cost"] == 1000.0
    assert js["total_materials_cost"] == 5000.0 and js["total_produced"] == 10
    assert js["missing_count"] == 0


def test_summarize_contracts_totals_series_and_missing():
    rows = [
        {"date": "2026-06-02", "total_cost": 5000.0, "total_sell": 8000.0, "broker_sell": 240.0, "profit": 2760.0, "missing": False},
        {"date": "2026-06-02", "total_cost": 1000.0, "total_sell": 1500.0, "broker_sell": 0.0, "profit": 500.0, "missing": True},
    ]
    s = industry_ledger.summarize_contracts(rows)
    assert s["total_profit"] == 3260.0 and s["count"] == 2 and s["missing_count"] == 1
    assert s["total_cost"] == 6000.0 and s["total_sell"] == 9500.0
    assert [x["date"] for x in s["series"]] == ["2026-06-02"]
    assert s["series"][0]["profit"] == 3260.0
