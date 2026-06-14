"""
Apply database migrations at API-container start.

Introduces Alembic to a database that historically used create_all:
  * managed DB (has alembic_version)        → upgrade to head
  * existing pre-Alembic DB (has schema)     → stamp the baseline, then upgrade
  * fresh DB                                 → upgrade to head (baseline builds it)

Best-effort: failures are logged, not fatal — create_all in database.py remains
the schema safety net, so a hiccup here never blocks the API from starting.
"""
import logging
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.core.database import engine

logger = logging.getLogger("app.migrate")

_BASELINE = "0001_baseline"

# the unbounded time-series tables to convert to Timescale hypertables
_HYPERTABLES = ("track_prices", "market_index_snapshots")


def _config() -> Config:
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return Config(os.path.join(backend_dir, "alembic.ini"))


def ensure_timescale() -> None:
    """
    Convert the unbounded tables to Timescale hypertables — but only once the
    timescaledb extension is available (i.e. after the db image is swapped to
    timescale/timescaledb). Idempotent, Postgres-only, best-effort: a no-op on
    plain Postgres / SQLite, and per-table so one failure can't half-convert.

    Take a database backup before first deploying the Timescale image — the
    conversion uses migrate_data and rewrites the table.
    """
    if engine.dialect.name != "postgresql":
        return
    with engine.connect() as conn:
        available = conn.execute(text(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'")).scalar()
    if not available:
        logger.info("timescale: extension unavailable — leaving tables as regular Postgres")
        return

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))

    for table in _HYPERTABLES:
        try:
            with engine.begin() as conn:
                is_hyper = conn.execute(text(
                    "SELECT 1 FROM timescaledb_information.hypertables "
                    "WHERE hypertable_name = :t"), {"t": table}).scalar()
                if is_hyper:
                    continue
                # a hypertable's partition column must be part of every unique
                # index / primary key, so widen the PK to (id, timestamp) first
                conn.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_pkey'))
                conn.execute(text(f'ALTER TABLE {table} ADD PRIMARY KEY (id, "timestamp")'))
                conn.execute(text(
                    f"SELECT create_hypertable('{table}', 'timestamp', "
                    "migrate_data => true, if_not_exists => true)"))
            logger.info("timescale: converted %s to a hypertable", table)
        except Exception as exc:
            logger.error("timescale: failed converting %s — %s", table, exc)


def run() -> None:
    cfg = _config()
    with engine.connect() as conn:
        insp = inspect(conn)
        has_version = insp.has_table("alembic_version")
        has_schema = insp.has_table("users")

    if has_version:
        logger.info("alembic: upgrading to head")
        command.upgrade(cfg, "head")
    elif has_schema:
        logger.info("alembic: adopting existing schema — stamp %s then upgrade", _BASELINE)
        command.stamp(cfg, _BASELINE)
        command.upgrade(cfg, "head")
    else:
        logger.info("alembic: fresh database — upgrading to head")
        command.upgrade(cfg, "head")

    ensure_timescale()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        run()
        logger.info("alembic: migrations applied")
    except Exception as exc:
        logger.error("alembic: migration step failed (create_all is the fallback) — %s", exc)


if __name__ == "__main__":
    main()
