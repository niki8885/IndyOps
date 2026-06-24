"""Add esi_market_orders table (character active buy/sell orders)

Holds each linked character's currently-open market orders, synced from ESI
(/characters/{id}/orders/) on the regular ESI sync. Active orders are a full
snapshot, so the sync replaces a character's rows each run. Powers Tracking →
Orders and the account dashboard's sell/buy/escrow totals.

Revision ID: 0028_esi_market_orders
Revises: 0027_market_forecasts
Create Date: 2026-06-24
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0028_esi_market_orders"
down_revision = "0027_market_forecasts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "esi_market_orders" not in insp.get_table_names():
        op.create_table(
            "esi_market_orders",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("character_id", sa.Integer(), nullable=False),
            sa.Column("order_id", sa.BigInteger(), nullable=False),
            sa.Column("type_id", sa.Integer(), nullable=True),
            sa.Column("region_id", sa.Integer(), nullable=True),
            sa.Column("location_id", sa.BigInteger(), nullable=True),
            sa.Column("is_buy_order", sa.Boolean(), nullable=True),
            sa.Column("price", sa.Float(), nullable=True),
            sa.Column("volume_total", sa.BigInteger(), nullable=True),
            sa.Column("volume_remain", sa.BigInteger(), nullable=True),
            sa.Column("min_volume", sa.BigInteger(), nullable=True),
            sa.Column("range", sa.String(20), nullable=True),
            sa.Column("duration", sa.Integer(), nullable=True),
            sa.Column("escrow", sa.Float(), nullable=True),
            sa.Column("issued", sa.DateTime(), nullable=True),
            sa.Column("synced_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("character_id", "order_id", name="uq_esi_market_order"),
        )
        op.create_index("ix_esi_market_orders_character_id", "esi_market_orders", ["character_id"])
        op.create_index("ix_esi_market_orders_type_id", "esi_market_orders", ["type_id"])


def downgrade() -> None:
    op.drop_index("ix_esi_market_orders_type_id", table_name="esi_market_orders")
    op.drop_index("ix_esi_market_orders_character_id", table_name="esi_market_orders")
    op.drop_table("esi_market_orders")
