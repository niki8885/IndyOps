"""
Trade optimizer collectors (Layers 1–2 of the data pipeline).

Two jobs at two cadences (see app.jobs):

* ``run_trade_orders_update`` (fast, ~10 min): bulk-fetch each hub's full order
  book, reduce to per-(hub, type) best buy/sell + sell-side depth, discover the
  candidate universe (category allowlist + presence + depth caps), join the
  history-derived liquidity/volatility from ``trade_type_stats``, apply the three
  Layer-2 filters, and upsert ``trade_candidates`` + ``station_trade_candidates``.

* ``run_trade_history_update`` (slow, ~6 h): pull per-(region, type) market
  history for the discovered universe and upsert daily volume + CV into
  ``trade_type_stats`` — the hand-off the fast job reads.

All ESI/SDE math beyond the adapters lives in pure ``app.services.trade``.
"""
import logging
from datetime import datetime, timezone

from app.core import config
from app.core.database import SessionLocal
from app.core.database_eve import EveSessionLocal
from app.core.trade_data import HUBS, jumps_between
from app.adapters import market
from app.repositories import eve_market, trade_repo
from app.services import trade

logger = logging.getLogger(__name__)


# ── order-book reduction & universe selection ───────────────────────────────

def _reduce_orders(orders: list[dict], station_id: int) -> dict[int, dict]:
    """Reduce a region's orders to per-type best sell / best buy / sell depth,
    keeping only orders physically located at ``station_id`` (the hub station)."""
    out: dict[int, dict] = {}
    for o in orders:
        if o.get("location_id") != station_id:
            continue
        tid = o.get("type_id")
        price = o.get("price")
        if tid is None or price is None:
            continue
        rec = out.get(tid)
        if rec is None:
            rec = out[tid] = {"best_sell": None, "best_buy": None, "sell_depth": 0.0}
        if o.get("is_buy_order"):
            if rec["best_buy"] is None or price > rec["best_buy"]:
                rec["best_buy"] = price
        else:
            if rec["best_sell"] is None or price < rec["best_sell"]:
                rec["best_sell"] = price
            rec["sell_depth"] += float(o.get("volume_remain") or 0)
    return out


def _select_universe(books: dict[str, dict], meta: dict[int, dict]) -> list[int]:
    """Type_ids that pass the category allowlist + presence/depth gates, capped
    to TRADE_MAX_UNIVERSE by descending total sell-side depth."""
    presence: dict[int, int] = {}
    total_depth: dict[int, float] = {}
    for reduced in books.values():
        for tid, rec in reduced.items():
            total_depth[tid] = total_depth.get(tid, 0.0) + rec["sell_depth"]
            if rec["sell_depth"] >= config.TRADE_MIN_BOOK_VOLUME:
                presence[tid] = presence.get(tid, 0) + 1

    chosen = []
    for tid, hubs_seen in presence.items():
        if hubs_seen < config.TRADE_MIN_HUBS:
            continue
        m = meta.get(tid)
        if not m or not m.get("published") or m.get("market_group_id") is None:
            continue
        if m.get("category_id") not in config.TRADE_CATEGORY_ALLOWLIST:
            continue
        chosen.append(tid)
    chosen.sort(key=lambda t: total_depth.get(t, 0.0), reverse=True)
    return chosen[: config.TRADE_MAX_UNIVERSE]


def _apply_volume_scores(rows: list[dict]) -> None:
    """Fill each row's volume_score from its daily_volume, normalised over the set."""
    scores = trade.volume_scores({i: (r["daily_volume"] or 0.0) for i, r in enumerate(rows)})
    for i, r in enumerate(rows):
        r["volume_score"] = scores.get(i, 0.0)


# ── fast job: orders → candidates ────────────────────────────────────────────

def run_trade_orders_update() -> dict:
    """Refresh trade_candidates + station_trade_candidates from live order books."""
    db = SessionLocal()
    eve_db = EveSessionLocal()
    summary = {"universe": 0, "cross_hub": 0, "station": 0, "errors": []}
    broker, tax, rate = config.TRADE_BROKER_FEE, config.TRADE_SALES_TAX, config.TRADE_ISK_PER_JUMP_M3
    minv, maxcv = config.TRADE_LIQUIDITY_MIN_VOLUME, config.TRADE_VOLATILITY_MAX_CV
    try:
        # 1) fetch + reduce each hub's whole order book
        books: dict[str, dict] = {}
        seen: set[int] = set()
        for name, hub in HUBS.items():
            orders = market.esi_region_orders_all(hub["region_id"], max_pages=config.TRADE_MAX_ORDER_PAGES)
            reduced = _reduce_orders(orders, hub["station_id"])
            books[name] = reduced
            seen.update(reduced.keys())

        # 2) discover the bounded universe
        meta = eve_market.types_market_meta(eve_db, list(seen))
        universe = _select_universe(books, meta)
        summary["universe"] = len(universe)

        # 3) per-hub history stats (liquidity/volatility) from the slow job
        stats = {name: trade_repo.load_type_stats(db, hub["region_id"], universe)
                 for name, hub in HUBS.items()}

        now = datetime.now(timezone.utc)

        # 4) cross-hub candidates (rank/filter on the patient margin)
        cross_rows: list[dict] = []
        for tid in universe:
            m = meta.get(tid) or {}
            vol_m3 = m.get("volume") or 0.0
            type_name = m.get("type_name")
            for buy_name, buy_hub in HUBS.items():
                src = books[buy_name].get(tid)
                if not src or src["best_sell"] is None:
                    continue
                buy_price = src["best_sell"]
                for sell_name, sell_hub in HUBS.items():
                    if sell_name == buy_name:
                        continue
                    dst = books[sell_name].get(tid)
                    if not dst or dst["best_sell"] is None:
                        continue
                    st = stats[sell_name].get(tid)   # liquidity at the *sell* hub
                    if not st:
                        continue                     # no history yet → fails liquidity
                    dvol = st.get("daily_volume") or 0.0
                    cv = st.get("volatility_cv")
                    jumps = jumps_between(buy_hub["station_id"], sell_hub["station_id"])
                    transport = trade.transport_cost_per_unit(vol_m3, jumps, rate)
                    patient = trade.patient_margin(buy_price, dst["best_sell"], broker, tax, transport)
                    if not trade.passes_filters(dvol, cv, patient["margin_pct"],
                                                min_volume=minv, max_cv=maxcv):
                        continue
                    if dst["best_buy"] is not None:
                        instant = trade.instant_margin(buy_price, dst["best_buy"], tax, transport)
                    else:
                        instant = {"profit_isk": None, "margin_pct": None}
                    cross_rows.append({
                        "item_id": tid,
                        "buy_hub": buy_hub["station_id"],
                        "sell_hub": sell_hub["station_id"],
                        "type_name": type_name,
                        "buy_price": buy_price,
                        "sell_price_patient": dst["best_sell"],
                        "sell_price_instant": dst["best_buy"],
                        "margin_pct_patient": patient["margin_pct"],
                        "margin_pct_instant": instant["margin_pct"],
                        "profit_isk_patient": patient["profit_isk"],
                        "profit_isk_instant": instant["profit_isk"],
                        "transport_cost": round(transport, 2),
                        "item_volume_m3": vol_m3,
                        "daily_volume": dvol,
                        "volatility_cv": cv,
                        "volume_score": None,
                        "updated_at": now,
                    })
        _apply_volume_scores(cross_rows)

        # 5) in-station flips (buy order ↔ sell order, broker ×2, no transport)
        station_rows: list[dict] = []
        for tid in universe:
            m = meta.get(tid) or {}
            type_name = m.get("type_name")
            for hub_name, hub in HUBS.items():
                rec = books[hub_name].get(tid)
                if not rec or rec["best_buy"] is None or rec["best_sell"] is None:
                    continue
                st = stats[hub_name].get(tid)
                if not st:
                    continue
                dvol = st.get("daily_volume") or 0.0
                cv = st.get("volatility_cv")
                res = trade.station_margin(rec["best_buy"], rec["best_sell"], broker, tax)
                if not trade.passes_filters(dvol, cv, res["margin_pct"],
                                            min_volume=minv, max_cv=maxcv):
                    continue
                station_rows.append({
                    "item_id": tid,
                    "hub": hub["station_id"],
                    "type_name": type_name,
                    "buy_price": rec["best_buy"],
                    "sell_price": rec["best_sell"],
                    "margin_pct": res["margin_pct"],
                    "profit_isk": res["profit_isk"],
                    "daily_volume": dvol,
                    "volatility_cv": cv,
                    "volume_score": None,
                    "updated_at": now,
                })
        _apply_volume_scores(station_rows)

        # 6) persist
        summary["cross_hub"] = trade_repo.upsert_trade_candidates(db, cross_rows)
        summary["station"] = trade_repo.upsert_station_candidates(db, station_rows)
        logger.info("trade orders: universe=%s cross=%s station=%s",
                    summary["universe"], summary["cross_hub"], summary["station"])
    except Exception as exc:
        db.rollback()
        logger.exception("trade orders update failed")
        summary["errors"].append(str(exc))
    finally:
        eve_db.close()
        db.close()
    return summary


# ── slow job: history → liquidity/volatility stats ───────────────────────────

def _history_universe(db) -> list[int]:
    """Type_ids to refresh history for: the current candidates, or — on cold
    start — discover from the hub order books, bounded by allowlist + cap."""
    type_ids = trade_repo.distinct_candidate_type_ids(db)
    if type_ids:
        return type_ids

    seen: set[int] = set()
    for hub in HUBS.values():
        orders = market.esi_region_orders_all(hub["region_id"], max_pages=config.TRADE_MAX_ORDER_PAGES)
        for o in orders:
            if o.get("location_id") == hub["station_id"] and o.get("type_id") is not None:
                seen.add(o["type_id"])
    eve_db = EveSessionLocal()
    try:
        meta = eve_market.types_market_meta(eve_db, list(seen))
    finally:
        eve_db.close()
    bounded = [t for t, m in meta.items()
               if m.get("published") and m.get("category_id") in config.TRADE_CATEGORY_ALLOWLIST]
    return bounded[: config.TRADE_MAX_UNIVERSE]


def run_trade_history_update() -> dict:
    """Refresh trade_type_stats (daily volume + CV) per (hub region, type)."""
    db = SessionLocal()
    summary = {"types": 0, "rows": 0, "errors": []}
    days = config.TRADE_HISTORY_DAYS
    try:
        type_ids = _history_universe(db)
        summary["types"] = len(type_ids)
        now = datetime.now(timezone.utc)
        rows: list[dict] = []
        for hub in HUBS.values():
            region = hub["region_id"]
            for tid in type_ids:
                hist = market.esi_region_history(region, tid)
                if not hist:
                    continue
                window = hist[-days:]
                rows.append({
                    "region_id": region,
                    "type_id": tid,
                    "daily_volume": round(trade.daily_volume(window), 2),
                    "volatility_cv": trade.volatility_cv(window),
                    "sample_days": len(window),
                    "computed_at": now,
                })
        summary["rows"] = trade_repo.upsert_type_stats(db, rows)
        logger.info("trade history: types=%s rows=%s", summary["types"], summary["rows"])
    except Exception as exc:
        db.rollback()
        logger.exception("trade history update failed")
        summary["errors"].append(str(exc))
    finally:
        db.close()
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(run_trade_history_update())
    print(run_trade_orders_update())
