"""
Scheduled background jobs (run by the dedicated worker container, not the API).

Each job runs under a Postgres session-level advisory lock so that only one
worker executes a given job at a time (idempotency / single-runner), and its
duration + outcome are logged. On non-Postgres engines the lock is a no-op.
"""
import logging
import time
from contextlib import contextmanager

from sqlalchemy import text

from app.core.database import SessionLocal, engine
from app.core.indices_data import INDEX_META, INDEX_ORDER
from app.repositories import cache_repo, market_repo
from app.services import index_report
from app.tasks.update_indices import run_index_update
from app.tasks.update_sde import run_sde_update
from app.tasks.update_tracking import run_tracking_update

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW = 10   # the API's default; other windows recompute on miss

# stable, distinct advisory-lock keys per job
_LOCK_KEYS = {"sde": 4101, "index": 4102, "tracking": 4103}


@contextmanager
def _advisory_lock(name: str):
    """
    Hold a Postgres advisory lock for the job's duration; yields whether it was
    acquired (False → another worker holds it). No-op (always True) off Postgres.
    """
    if engine.dialect.name != "postgresql":
        yield True
        return
    key = _LOCK_KEYS[name]
    conn = engine.connect()
    got = False
    try:
        got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar())
        yield got
    finally:
        try:
            if got:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
        except Exception:
            pass
        conn.close()


def _run(name: str, fn):
    """Run ``fn`` under the advisory lock with duration logging; never raises."""
    start = time.monotonic()
    try:
        with _advisory_lock(name) as acquired:
            if not acquired:
                logger.info("job %s: another worker holds the lock — skipping", name)
                return
            logger.info("job %s: start", name)
            result = fn()
            logger.info("job %s: done in %.1fs — %s", name, time.monotonic() - start, result)
    except Exception as exc:
        logger.error("job %s: failed after %.1fs — %s", name, time.monotonic() - start, exc)


def warm_index_cache(db, window: int = _DEFAULT_WINDOW) -> int:
    """Pre-compute + store the detail payload for every index. Returns count warmed."""
    warmed = 0
    for key in INDEX_ORDER:
        df = market_repo.index_snapshots_df(db, key)
        if df.empty:
            continue
        payload = index_report.compute_index_payload(
            df, key, INDEX_META[key]["label"], INDEX_META[key]["kind"], window)
        cache_repo.set_cached(db, "index", key, window, payload)
        warmed += 1
    return warmed


def job_index():
    def _collect_and_warm():
        result = run_index_update()
        db = SessionLocal()
        try:
            warmed = warm_index_cache(db)
        finally:
            db.close()
        return {"collect": result, "cache_warmed": warmed}

    _run("index", _collect_and_warm)


def job_tracking():
    _run("tracking", run_tracking_update)


def job_sde():
    _run("sde", run_sde_update)


def register(scheduler) -> None:
    """Attach the cron jobs to a scheduler (worker process owns it)."""
    scheduler.add_job(job_sde, "cron", hour=3, minute=0, id="sde_update_job", replace_existing=True)
    scheduler.add_job(job_index, "cron", minute=2, id="index_update_job", replace_existing=True)
    scheduler.add_job(job_tracking, "cron", minute=7, id="tracking_update_job", replace_existing=True)
