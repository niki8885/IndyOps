"""
Dedicated background-worker entrypoint.

Runs the scheduled collectors in their own process/container, out of the API
process, so a slow ESI/Fuzzwork fetch never blocks request handling. Start with:

    python -m app.worker
"""
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from app.jobs import register

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app.worker")


def main() -> None:
    scheduler = BlockingScheduler(timezone="UTC")
    register(scheduler)
    logger.info("IndyOps worker started — jobs: %s", [j.id for j in scheduler.get_jobs()])
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("worker shutting down")
        raise


if __name__ == "__main__":
    main()
