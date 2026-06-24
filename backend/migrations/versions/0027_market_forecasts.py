"""Add market_forecasts table (IO-49 precomputed volume/price forecasts)

Stores one precomputed forecast per (region, type, horizon) written by the
``forecasts`` worker job over the liquid universe, so the /market/forecast read is
a row lookup instead of an on-demand recompute. The full forecast payload is kept
as JSON; summary columns (signal / chosen models / MASE / avg turnover) stay
queryable for future demand screeners. Current-state upsert — no backfill needed.

Revision ID: 0027_market_forecasts
Revises: 0026_haul_jita_buy_volume
Create Date: 2026-06-24
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0027_market_forecasts"
down_revision = "0026_haul_jita_buy_volume"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "market_forecasts" not in insp.get_table_names():
        op.create_table(
            "market_forecasts",
            sa.Column("region_id", sa.Integer(), primary_key=True),
            sa.Column("type_id", sa.Integer(), primary_key=True),
            sa.Column("horizon", sa.Integer(), primary_key=True),
            sa.Column("vol_model", sa.String(20), nullable=True),
            sa.Column("vol_mase", sa.Float(), nullable=True),
            sa.Column("price_model", sa.String(20), nullable=True),
            sa.Column("price_mase", sa.Float(), nullable=True),
            sa.Column("signal_action", sa.String(12), nullable=True),
            sa.Column("signal_score", sa.Float(), nullable=True),
            sa.Column("avg_turnover", sa.Float(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("computed_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_market_forecasts_computed_at", "market_forecasts", ["computed_at"])


def downgrade() -> None:
    op.drop_index("ix_market_forecasts_computed_at", table_name="market_forecasts")
    op.drop_table("market_forecasts")
