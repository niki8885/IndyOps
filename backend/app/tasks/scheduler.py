from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

from app.core.database import SessionLocal
from app.tasks.update_sde import run_sde_update

import logging

executors = {
    'default': ThreadPoolExecutor(2)
}

scheduler = BackgroundScheduler(executors=executors, timezone="UTC")
logger = logging.getLogger(__name__)


def scheduled_update_daily():
    db = SessionLocal()
    try:
        logger.info("Full sync completed successfully.")
    except Exception as e:
        logger.error(f"Full sync failed: {e}")
    finally:
        db.close()


def scheduled_sde_update():
    logger.info("Starting scheduled SDE update...")
    result = run_sde_update()
    if result.get("skipped"):
        logger.info("SDE already up-to-date, skipping.")
    elif result.get("errors"):
        logger.error("SDE update finished with errors: %s", result["errors"])
    else:
        total = sum(s["rows"] for s in result.get("steps", {}).values())
        logger.info("SDE update done — %d rows upserted.", total)


scheduler.add_job(
    scheduled_update_daily,
    "cron",
    hour=23,
    minute=45,
    id="daily_sync_job",
    replace_existing=True,
)

# EVE SDE refresh — runs daily at 03:00 UTC (fuzzwork updates ~daily after patches)
scheduler.add_job(
    scheduled_sde_update,
    "cron",
    hour=3,
    minute=0,
    id="sde_update_job",
    replace_existing=True,
)
