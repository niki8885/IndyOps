"""Add trade_candidates, station_trade_candidates, trade_type_stats (trade optimizer data layer)

Revision ID: 0011_trade_candidates
Revises: 0010_production_status_events
Create Date: 2026-06-18

These are current-state upsert tables (re-overwritten each collector run), not
append-only time series — so they stay regular Postgres tables and are NOT
converted to Timescale hypertables.
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_trade_candidates"
down_revision = "0010_production_status_events"
branch_labels = None
depends_on = None

_NOW_SQL = "NOW()"  # server-side default timestamp, reused across the upsert tables


def upgrade() -> None:
    op.create_table(
        "trade_candidates",
        sa.Column("item_id", sa.Integer(), primary_key=True),
        sa.Column("buy_hub", sa.BigInteger(), primary_key=True),
        sa.Column("sell_hub", sa.BigInteger(), primary_key=True),
        sa.Column("type_name", sa.String(200), nullable=True),
        sa.Column("buy_price", sa.Float(), nullable=True),
        sa.Column("sell_price_patient", sa.Float(), nullable=True),
        sa.Column("sell_price_instant", sa.Float(), nullable=True),
        sa.Column("margin_pct_patient", sa.Float(), nullable=True),
        sa.Column("margin_pct_instant", sa.Float(), nullable=True),
        sa.Column("profit_isk_patient", sa.Float(), nullable=True),
        sa.Column("profit_isk_instant", sa.Float(), nullable=True),
        sa.Column("transport_cost", sa.Float(), nullable=True),
        sa.Column("item_volume_m3", sa.Float(), nullable=True),
        sa.Column("daily_volume", sa.Float(), nullable=True),
        sa.Column("volatility_cv", sa.Float(), nullable=True),
        sa.Column("volume_score", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text(_NOW_SQL)),
    )
    op.create_index("ix_trade_candidates_updated_at", "trade_candidates", ["updated_at"])
    op.create_index("ix_trade_candidates_margin_patient", "trade_candidates", ["margin_pct_patient"])

    op.create_table(
        "station_trade_candidates",
        sa.Column("item_id", sa.Integer(), primary_key=True),
        sa.Column("hub", sa.BigInteger(), primary_key=True),
        sa.Column("type_name", sa.String(200), nullable=True),
        sa.Column("buy_price", sa.Float(), nullable=True),
        sa.Column("sell_price", sa.Float(), nullable=True),
        sa.Column("margin_pct", sa.Float(), nullable=True),
        sa.Column("profit_isk", sa.Float(), nullable=True),
        sa.Column("daily_volume", sa.Float(), nullable=True),
        sa.Column("volatility_cv", sa.Float(), nullable=True),
        sa.Column("volume_score", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text(_NOW_SQL)),
    )
    op.create_index("ix_station_trade_candidates_updated_at", "station_trade_candidates", ["updated_at"])

    op.create_table(
        "trade_type_stats",
        sa.Column("region_id", sa.Integer(), primary_key=True),
        sa.Column("type_id", sa.Integer(), primary_key=True),
        sa.Column("daily_volume", sa.Float(), nullable=True),
        sa.Column("volatility_cv", sa.Float(), nullable=True),
        sa.Column("sample_days", sa.Integer(), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.text(_NOW_SQL)),
    )
    op.create_index("ix_trade_type_stats_computed_at", "trade_type_stats", ["computed_at"])


def downgrade() -> None:
    op.drop_index("ix_trade_type_stats_computed_at", table_name="trade_type_stats")
    op.drop_table("trade_type_stats")
    op.drop_index("ix_station_trade_candidates_updated_at", table_name="station_trade_candidates")
    op.drop_table("station_trade_candidates")
    op.drop_index("ix_trade_candidates_margin_patient", table_name="trade_candidates")
    op.drop_index("ix_trade_candidates_updated_at", table_name="trade_candidates")
    op.drop_table("trade_candidates")
