"""Realized manufacturing profit via a FIFO cost ledger (Tracking → Industry).

Pure stdlib, no DB/network — the router assembles a chronologically-sortable list of
events (market buys, completed manufacturing jobs, market sells) and this module walks
them through per-item FIFO queues to attribute material costs and realize build profit.
See [[indyops-service-layering]] and the trade-side cousin [[indyops-tracking-profit-tracker]].

The ledger is account-wide (all of a user's characters pooled into one inventory), which
mirrors how industry materials are usually consolidated and minimises false "missing
inputs". A lot is ``[qty, unit_cost, origin, job_id, missing]``:

  - a **buy** pushes a lot (origin ``"buy"``) at unit_cost = price + broker fee per unit;
  - a **build** consumes input lots FIFO (any shortfall ⇒ the job is flagged ``missing``,
    that portion has no cost basis), then pushes a built lot (origin ``"build"``) whose
    unit_cost = (materials + job + copy cost) / produced, carrying the ``missing`` flag;
  - a **sell** consumes lots FIFO — built-origin units realize manufacturing profit and
    bump the source job's ``sold`` (bought-origin units are trade, handled by the Market
    tab); built units whose source job was ``missing`` are sold but not counted in profit.

ESI exposes only ~30 days of transactions, so material buys older than that window are
absent and the jobs that used them read as "missing inputs" until history accumulates.
"""
from __future__ import annotations
from typing import Optional

# build event tie-break: a same-timestamp buy backs a build, a build backs a sell /
# contract sale (both consume finished goods, so they order after builds)
_ORDER = {"buy": 0, "build": 1, "sell": 2, "contract_sell": 2}


def _day(value) -> Optional[str]:
    """ISO date (``YYYY-MM-DD``) of a datetime, or None."""
    return value.date().isoformat() if value is not None else None


def run_ledger(events: list[dict], include_missing: bool = False) -> dict:
    """Walk industry/market ``events`` through a FIFO cost ledger.

    Returns ``{"jobs": [...], "manufacturing": [...]}`` — one job row per build (with
    realized material cost, unit cost, produced/sold/consumed and a ``missing`` flag) and
    one manufacturing-profit row per sell that consumed built units.

    ``include_missing`` controls whether sales of built units whose source job had an
    incomplete cost basis are counted into manufacturing profit. Default ``False`` (the
    conservative behaviour: don't count an overstated-margin sale). When ``True`` those
    sales are realized too and the row carries ``missing: True`` so the UI can flag it."""
    ordered = sorted(events, key=lambda e: (e.get("date"), _ORDER.get(e.get("kind"), 9)))

    queues: dict = {}        # type_id -> list of lots [qty, unit_cost, origin, job_id, missing]
    jobs_by_id: dict = {}    # job_id -> job row (mutated for sold / consumed)
    jobs: list = []
    manufacturing: list = []
    contracts: list = []

    for e in ordered:
        kind = e.get("kind")

        if kind == "buy":
            queues.setdefault(e["type_id"], []).append(
                [int(e.get("qty") or 0), float(e.get("unit_cost") or 0.0), "buy", None, False])
            continue

        if kind == "build":
            materials_cost = 0.0
            missing = False
            missing_reason = None
            for m in e.get("inputs", []):
                need = int(m.get("qty") or 0)
                q = queues.get(m["type_id"]) or []
                while need > 0 and q:
                    lot = q[0]
                    take = min(need, lot[0])
                    materials_cost += take * lot[1]
                    need -= take
                    lot[0] -= take
                    if lot[2] == "build" and lot[3] is not None:   # a built input was consumed
                        src = jobs_by_id.get(lot[3])
                        if src:
                            src["consumed"] += take
                    if lot[0] <= 0:
                        q.pop(0)
                if need > 0:                                       # shortfall — no cost basis
                    missing = True
                    missing_reason = "untracked_inputs"

            # A producing build (manufacturing/reaction) whose bill-of-materials couldn't be
            # resolved — no SDE BOM rows or no blueprint id (bom_known=False) — has no cost
            # basis at all. Flag it missing instead of reporting a near-free build; a
            # custom_unit_price below still clears it. bom_known defaults True, so callers that
            # don't supply it and non-producing activities (copying/research) are unaffected.
            if e.get("produces", True) and not e.get("bom_known", True):
                missing = True
                missing_reason = "no_bom"

            produced = int(e.get("product_qty") or 0)
            job_cost = float(e.get("job_cost") or 0.0)
            copy_cost = float(e.get("copy_cost") or 0.0)
            runs = int(e.get("runs") or 0)
            custom = e.get("custom_unit_price")
            if custom is not None and produced > 0:
                # user-supplied cost basis (Custom Unit Price) — overrides FIFO, clears missing
                unit_cost = float(custom)
                total_cost = unit_cost * produced
                materials_cost = max(0.0, total_cost - job_cost - copy_cost)
                missing = False
                missing_reason = None
            else:
                total_cost = materials_cost + job_cost + copy_cost
                unit_cost = total_cost / produced if produced else 0.0
            row = {
                "job_id": e.get("job_id"),
                "date": _day(e.get("date")),
                "completed_at": e.get("completed_at"),
                "owner": e.get("owner"),
                "activity": e.get("activity", "Manufacturing"),
                "blueprint_name": e.get("blueprint_name"),
                "product_name": e.get("product_name"),
                "job_cost": round(job_cost, 2),
                "materials_cost": round(materials_cost, 2),
                "copy_cost": round(copy_cost, 2),
                "unit_cost": round(unit_cost, 2),
                "runs": runs,
                "runs_missing": runs if missing else 0,
                "produced": produced,
                "sold": 0,
                "consumed": 0,
                "missing": missing,
                "missing_reason": missing_reason,   # 'no_bom' | 'untracked_inputs' | None
                "custom_unit_price": float(custom) if custom is not None else None,
            }
            jobs_by_id[e.get("job_id")] = row
            jobs.append(row)
            # only manufacturing / reactions yield a sellable lot that feeds the profit table;
            # copying / research / invention show their cost in the jobs table but make no lot.
            if e.get("produces", True) and produced > 0:
                queues.setdefault(e["product_type_id"], []).append(
                    [produced, unit_cost, "build", e.get("job_id"), missing])
            continue

        if kind == "sell":
            type_id = e["type_id"]
            need = int(e.get("qty") or 0)
            price = float(e.get("unit_price") or 0.0)
            broker_pct = float(e.get("broker_pct") or 0.0)
            tax_pct = float(e.get("tax_pct") or 0.0)
            q = queues.get(type_id) or []
            built_units = 0
            built_cost = 0.0
            missing_any = False
            while need > 0 and q:
                lot = q[0]
                take = min(need, lot[0])
                need -= take
                lot[0] -= take
                if lot[2] == "build":
                    src = jobs_by_id.get(lot[3])
                    if src:
                        src["sold"] += take
                    # complete cost basis always counts; missing only when include_missing
                    if not lot[4] or include_missing:
                        built_units += take
                        built_cost += take * lot[1]
                        if lot[4]:
                            missing_any = True
                if lot[0] <= 0:
                    q.pop(0)
            if built_units > 0:
                sell_value = built_units * price
                broker_sell = sell_value * broker_pct / 100.0
                sales_tax = sell_value * tax_pct / 100.0
                profit = sell_value - built_cost - broker_sell - sales_tax
                manufacturing.append({
                    "date": _day(e.get("date")),
                    "type_id": type_id,
                    "name": e.get("name"),
                    "units": built_units,
                    "unit_build": round(built_cost / built_units, 2),
                    "unit_sell": round(price, 2),
                    "total_build": round(built_cost, 2),
                    "total_sell": round(sell_value, 2),
                    "broker_sell": round(broker_sell, 2),
                    "sales_tax": round(sales_tax, 2),
                    "profit": round(profit, 2),
                    "margin": round(profit / built_cost * 100, 2) if built_cost else None,
                    "missing": missing_any,
                })
            continue

        if kind == "contract_sell":
            # a sold item-exchange contract: the bundle's items consume cost basis from the
            # same FIFO queues; the contract price is the bundle's sell value.
            total_cost = 0.0
            missing = False
            for m in e.get("items", []):
                need = int(m.get("qty") or 0)
                q = queues.get(m["type_id"]) or []
                while need > 0 and q:
                    lot = q[0]
                    take = min(need, lot[0])
                    total_cost += take * lot[1]
                    need -= take
                    lot[0] -= take
                    if lot[2] == "build" and lot[3] is not None:
                        src = jobs_by_id.get(lot[3])
                        if src:
                            src["sold"] += take
                    if lot[0] <= 0:
                        q.pop(0)
                if need > 0:                  # part of the bundle has no tracked cost basis
                    missing = True
            price = float(e.get("price") or 0.0)
            broker = float(e.get("broker") or 0.0)
            profit = price - total_cost - broker
            contracts.append({
                "date": _day(e.get("date")),
                "contract_id": e.get("contract_id"),
                "character": e.get("character"),
                "acceptor": e.get("acceptor"),
                "title": e.get("title"),
                "note": e.get("note"),
                "total_cost": round(total_cost, 2),
                "total_sell": round(price, 2),
                "broker_sell": round(broker, 2),
                "sales_tax": 0.0,             # item-exchange contracts pay no sales tax
                "profit": round(profit, 2),
                "margin": round(profit / total_cost * 100, 2) if total_cost else None,
                "missing": missing,
            })
            continue

    return {"jobs": jobs, "manufacturing": manufacturing, "contracts": contracts}


def summarize_manufacturing(rows: list[dict]) -> dict:
    """Aggregate realized manufacturing-profit rows into totals + a per-day profit series."""
    total_build = total_sell = total_broker = total_tax = total_profit = 0.0
    units = 0
    series: dict = {}
    for r in rows:
        total_build += r["total_build"]
        total_sell += r["total_sell"]
        total_broker += r["broker_sell"]
        total_tax += r["sales_tax"]
        total_profit += r["profit"]
        units += r["units"]
        day = r.get("date")
        if day:
            s = series.setdefault(day, {"date": day, "profit": 0.0, "sell": 0.0})
            s["profit"] += r["profit"]
            s["sell"] += r["total_sell"]
    for s in series.values():
        s["profit"] = round(s["profit"], 2)
        s["sell"] = round(s["sell"], 2)

    # win/loss + risk metrics: a "win" is a realized manufacturing sale with positive profit.
    wins = [r["profit"] for r in rows if r["profit"] > 0]
    losses = [r["profit"] for r in rows if r["profit"] < 0]
    gross_loss = -sum(losses)
    n_days = len(series)

    return {
        "total_build": round(total_build, 2),
        "total_sell": round(total_sell, 2),
        "total_broker": round(total_broker, 2),
        "total_tax": round(total_tax, 2),
        "total_profit": round(total_profit, 2),
        "units": units,
        "trade_count": len(rows),
        "avg_margin": round(total_profit / total_build * 100, 2) if total_build else None,
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(rows) * 100, 1) if rows else None,
        "profit_factor": round(sum(wins) / gross_loss, 2) if gross_loss else None,
        "avg_profit": round(total_profit / len(rows), 2) if rows else None,
        "profit_per_day": round(total_profit / n_days, 2) if n_days else None,
        "series": sorted(series.values(), key=lambda x: x["date"]),
    }


def summarize_jobs(jobs: list[dict]) -> dict:
    """Headline metrics for the completed-jobs table."""
    return {
        "job_count": len(jobs),
        "total_job_cost": round(sum(j["job_cost"] for j in jobs), 2),
        "total_materials_cost": round(sum(j["materials_cost"] for j in jobs), 2),
        "total_produced": sum(j["produced"] for j in jobs),
        "missing_count": sum(1 for j in jobs if j["missing"]),
    }


def summarize_contracts(rows: list[dict]) -> dict:
    """Aggregate realized contract-sale rows into totals + a per-day profit series."""
    total_cost = total_sell = total_broker = total_profit = 0.0
    series: dict = {}
    for r in rows:
        total_cost += r["total_cost"]
        total_sell += r["total_sell"]
        total_broker += r["broker_sell"]
        total_profit += r["profit"]
        day = r.get("date")
        if day:
            s = series.setdefault(day, {"date": day, "profit": 0.0, "sell": 0.0})
            s["profit"] += r["profit"]
            s["sell"] += r["total_sell"]
    for s in series.values():
        s["profit"] = round(s["profit"], 2)
        s["sell"] = round(s["sell"], 2)
    return {
        "total_cost": round(total_cost, 2),
        "total_sell": round(total_sell, 2),
        "total_broker": round(total_broker, 2),
        "total_profit": round(total_profit, 2),
        "count": len(rows),
        "missing_count": sum(1 for r in rows if r.get("missing")),
        "avg_margin": round(total_profit / total_cost * 100, 2) if total_cost else None,
        "series": sorted(series.values(), key=lambda x: x["date"]),
    }
