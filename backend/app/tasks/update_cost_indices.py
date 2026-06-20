from __future__ import annotations
import logging
from app.adapters import market
from app.core.database import SessionLocal, SystemCostIndex
from app.core.timeutil import utcnow

logger = logging.getLogger(__name__)


def run_cost_index_update() -> dict:
    """Full-snapshot refresh of ``system_cost_indices``. Returns a summary dict."""
    db = SessionLocal()
    summary = {"systems": 0, "rows": 0, "errors": []}
    try:
        table = market.esi_cost_indices()  # {system_id: {activity: index}}
        now = utcnow()
        rows = [
            {
                "solar_system_id": int(sid),
                "activity": str(act),
                "cost_index": float(idx or 0.0),
                "updated_at": now,
            }
            for sid, acts in table.items()
            for act, idx in acts.items()
        ]
        db.query(SystemCostIndex).delete()
        if rows:
            db.bulk_insert_mappings(SystemCostIndex, rows)
        db.commit()
        summary["systems"] = len(table)
        summary["rows"] = len(rows)
        logger.info("Cost-index update stored: %d systems, %d rows", len(table), len(rows))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error("Cost-index update failed: %s", exc)
        summary["errors"].append(str(exc))
    finally:
        db.close()
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(run_cost_index_update())
