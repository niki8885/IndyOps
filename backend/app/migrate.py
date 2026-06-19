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
from app.core.database import engine, Base
logger = logging.getLogger("app.migrate")

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
        except Exception:
            logger.exception("timescale: failed converting %s", table)


def _column_default_sql(col) -> str | None:
    """A SQL DEFAULT literal for a model column (so adding a NOT NULL column to a
    populated table doesn't fail), or None. Prefer the scalar Python ``default=``
    (unambiguous — strings get quoted), falling back to a ``server_default`` SQL
    expression (rendered raw)."""
    d = col.default
    if d is not None and getattr(d, "is_scalar", False):
        v = d.arg
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        return "'" + str(v).replace("'", "''") + "'"
    sd = col.server_default
    if sd is not None and getattr(sd, "arg", None) is not None:
        return str(getattr(sd.arg, "text", sd.arg))
    return None


def reconcile_columns() -> None:
    """``create_all`` builds *missing tables* but never ALTERs existing ones — so a
    model column (or index) added to a pre-existing table is silently absent (and
    every query on that table 500s). Add any such columns + indexes, best-effort, so
    the schema matches the models even when Alembic didn't run. Postgres/SQLite only.
    """
    if engine.dialect.name not in ("postgresql", "sqlite"):
        return
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            continue  # create_all handles brand-new tables
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            try:
                ddl = f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {col.type.compile(dialect=engine.dialect)}'
                default = _column_default_sql(col)
                if default is not None:
                    ddl += f" DEFAULT {default}"
                if not col.nullable:
                    ddl += " NOT NULL"
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                logger.info("reconcile: added column %s.%s", table.name, col.name)
            except Exception:
                logger.exception("reconcile: failed adding %s.%s", table.name, col.name)

        have_idx = {i["name"] for i in insp.get_indexes(table.name)}
        for idx in table.indexes:
            if not idx.name or idx.name in have_idx:
                continue
            try:
                cols = ", ".join(f'"{c.name}"' for c in idx.columns)
                with engine.begin() as conn:
                    conn.execute(text(f'CREATE INDEX IF NOT EXISTS {idx.name} ON {table.name} ({cols})'))
                logger.info("reconcile: added index %s", idx.name)
            except Exception:
                logger.exception("reconcile: failed adding index %s", idx.name)


def run() -> None:
    cfg = _config()
    # create_all (import-time, RUN_DB_BOOTSTRAP) creates missing TABLES; this fills in
    # columns added to already-existing tables so the schema always matches the models
    # regardless of Alembic's outcome.
    reconcile_columns()

    with engine.connect() as conn:
        has_version = inspect(conn).has_table("alembic_version")

    if has_version:
        logger.info("alembic: upgrading to head")
        try:
            command.upgrade(cfg, "head")
        except Exception:
            logger.exception("alembic upgrade failed; schema reconciled — stamping head")
            command.stamp(cfg, "head")
    else:
        logger.info("alembic: no version table — stamping head (schema built by create_all)")
        command.stamp(cfg, "head")

    ensure_timescale()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        run()
        logger.info("alembic: migrations applied")
    except Exception:
        logger.exception("alembic: migration step failed (create_all is the fallback)")


if __name__ == "__main__":
    main()
