"""
Precompute volume/price forecasts for the liquid universe (IO-49, cache-warm job).

Runs the native forecast-engine (SARIMA/Holt-Winters/Croston/ARIMA panel, with a
Python fallback) over the most-liquid Jita items and upserts ``market_forecasts``,
so the /market/forecast read is a row lookup instead of an on-demand recompute.
Bounded (FORECAST_MAX_ITEMS) because each item pulls ~13mo of ESI history; other
regions and the 7/90-day horizons stay on-demand (the native compute is ~0.1s).

Universe comes from ``trade_type_stats`` (populated by the trade-history job), so
this depends on that having run at least once.
"""
import logging
from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.core.database_eve import EveSessionLocal
from app.adapters import forecast_engine, market
from app.repositories import eve_market, forecast_repo, trade_repo

logger = logging.getLogger(__name__)

FORECAST_REGION = 10000002    # The Forge / Jita — the default hub the UI opens on
FORECAST_HORIZON = 30         # the UI default; 7/90 recompute on demand
FORECAST_MIN_VOLUME = 50.0    # daily-volume floor for the universe
FORECAST_MAX_ITEMS = 150      # cap (per-item ESI history fetch keeps the run bounded)
_MIN_HISTORY = 30             # days needed to backtest


def run_forecast_update() -> dict:
    """Refresh market_forecasts for the most-liquid Jita types at the default horizon."""
    db = SessionLocal()
    eve_db = EveSessionLocal()
    summary = {"universe": 0, "rows": 0, "errors": []}
    try:
        liquid = trade_repo.liquid_type_ids(
            db, FORECAST_REGION, FORECAST_MIN_VOLUME, FORECAST_MAX_ITEMS)
        type_ids = [t for t, _ in liquid]
        summary["universe"] = len(type_ids)
        if not type_ids:
            logger.info("forecasts: no liquid Jita types yet (run trade history first)")
            return summary

        region_name = eve_market.region_name(eve_db, FORECAST_REGION)
        now = datetime.now(timezone.utc)
        rows: list[dict] = []
        for tid in type_ids:
            try:
                hist = market.esi_region_history_full(FORECAST_REGION, tid)
                if not hist or len(hist) < _MIN_HISTORY:
                    continue
                info = eve_market.type_info(eve_db, tid)
                label = info["type_name"] if info else str(tid)
                payload, _engine = forecast_engine.compute(
                    hist, tid, label, region_name, FORECAST_HORIZON)
                v = payload.get("volume") or {}
                p = payload.get("price") or {}
                sig = payload.get("signal") or {}
                tp = [x for x in (payload.get("isk_turnover") or {}).get("p50", []) if x is not None]
                rows.append({
                    "region_id": FORECAST_REGION, "type_id": tid, "horizon": FORECAST_HORIZON,
                    "vol_model": v.get("model"),
                    "vol_mase": (v.get("backtest") or {}).get("mase"),
                    "price_model": p.get("model"),
                    "price_mase": (p.get("backtest") or {}).get("mase"),
                    "signal_action": sig.get("action"), "signal_score": sig.get("score"),
                    "avg_turnover": (sum(tp) / len(tp)) if tp else None,
                    "payload": payload, "computed_at": now,
                })
            except Exception as exc:
                summary["errors"].append(f"{tid}: {exc}")
        summary["rows"] = forecast_repo.upsert_forecasts(db, rows)
        logger.info("forecasts: universe=%s rows=%s errors=%s",
                    summary["universe"], summary["rows"], len(summary["errors"]))
    except Exception as exc:
        db.rollback()
        logger.exception("forecast update failed")
        summary["errors"].append(str(exc))
    finally:
        eve_db.close()
        db.close()
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(run_forecast_update())
