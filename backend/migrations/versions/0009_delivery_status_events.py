"""Add delivery_status_events (delivery status history / tracking)

Revision ID: 0009_delivery_status_events
Revises: 0008_deliveries
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_delivery_status_events"
down_revision = "0008_deliveries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_status_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("delivery_id", sa.Integer(), sa.ForeignKey("deliveries.id"), nullable=False),
        sa.Column("from_status", sa.String(12), nullable=True),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_delivery_status_events_delivery_id", "delivery_status_events", ["delivery_id"])
    op.create_index("ix_delivery_status_events_at", "delivery_status_events", ["at"])


def downgrade() -> None:
    op.drop_index("ix_delivery_status_events_at", table_name="delivery_status_events")
    op.drop_index("ix_delivery_status_events_delivery_id", table_name="delivery_status_events")
    op.drop_table("delivery_status_events")
