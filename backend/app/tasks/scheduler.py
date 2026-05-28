from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

from app.core.database import SessionLocal

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


scheduler.add_job(
    scheduled_update_daily,
    "cron",
    hour=23,
    minute=45,
    id="daily_sync_job",
    replace_existing=True,
)
