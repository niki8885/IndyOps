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
from app.adapters import analytics_engine
from app.repositories import cache_repo, market_repo
from app.tasks.update_indices import run_index_update
from app.tasks.update_cost_indices import run_cost_index_update
from app.tasks.update_sde import run_sde_update
from app.tasks.update_tracking import run_tracking_update
from app.tasks.update_esi import sync_all_active
from app.tasks.update_trade import run_trade_orders_update, run_trade_history_update, run_haul_scan_update
from app.tasks.evaluate_alerts import run_alert_evaluation

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW = 10   # the API's default; other windows recompute on miss

# stable, distinct advisory-lock keys per job
_LOCK_KEYS = {
    "sde": 4101, "index": 4102, "tracking": 4103, "esi": 4104,
    "trade_orders": 4105, "trade_history": 4106, "alerts": 4107,
    "cost_idx": 4108, "haul_scan": 4109,
}


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
    except Exception:
        logger.exception("job %s: failed after %.1fs", name, time.monotonic() - start)


def warm_index_cache(db, window: int = _DEFAULT_WINDOW) -> int:
    """Pre-compute + store the detail payload for every index. Returns count warmed."""
    warmed = 0
    for key in INDEX_ORDER:
        df = market_repo.index_snapshots_df(db, key)
        if df.empty:
            continue
        payload, engine = analytics_engine.compute(
            df, key, INDEX_META[key]["label"], INDEX_META[key]["kind"], window)
        payload["engine"] = engine
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


def job_esi():
    _run("esi", sync_all_active)


def job_trade_orders():
    _run("trade_orders", run_trade_orders_update)


def job_trade_history():
    _run("trade_history", run_trade_history_update)


def job_alerts():
    _run("alerts", run_alert_evaluation)


def job_cost_indices():
    _run("cost_idx", run_cost_index_update)


def job_haul_scan():
    _run("haul_scan", run_haul_scan_update)


def register(scheduler) -> None:
    """Attach the cron jobs to a scheduler (worker process owns it)."""
    scheduler.add_job(job_sde, "cron", hour=3, minute=0, id="sde_update_job", replace_existing=True)
    scheduler.add_job(job_index, "cron", minute=2, id="index_update_job", replace_existing=True)
    scheduler.add_job(job_tracking, "cron", minute=7, id="tracking_update_job", replace_existing=True)
    scheduler.add_job(job_esi, "cron", minute="*/30", id="esi_sync_job", replace_existing=True)
    scheduler.add_job(job_trade_orders, "cron", minute="*/10", id="trade_orders_job", replace_existing=True)
    scheduler.add_job(job_trade_history, "cron", hour="*/6", minute=15, id="trade_history_job", replace_existing=True)
    scheduler.add_job(job_alerts, "cron", minute="*/5", id="alerts_eval_job", replace_existing=True)
    scheduler.add_job(job_cost_indices, "cron", hour="*/6", minute=20, id="cost_index_job", replace_existing=True)
    # Haul scanner: every 20 min (offset). C-J is slow but the universe is capped
    # (TRADE_HAUL_MAX_ITEMS), so each run stays short; tune the cadence here.
    scheduler.add_job(job_haul_scan, "cron", minute="8,28,48", id="haul_scan_job", replace_existing=True)
