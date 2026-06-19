"""Agenda — price/volume alerts + notifications feed

Revision ID: 0015_agenda_alerts
Revises: 0014_mining_journal
Create Date: 2026-06-19

Backs the Agenda page: user-defined financial alerts on commodity indices and
tracked items (price above/below a value, or a % move in price/volume over a
window), plus the in-app notifications feed those alerts deliver into.
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_agenda_alerts"
down_revision = "0014_mining_journal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_kind", sa.String(10), nullable=False),
        sa.Column("index_key", sa.String(20), nullable=True),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("place_id", sa.Integer(), nullable=True),
        sa.Column("metric", sa.String(10), nullable=False, server_default="price"),
        sa.Column("condition", sa.String(12), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("repeat", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("last_value", sa.Float(), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_price_alerts_user_id", "price_alerts", ["user_id"])
    op.create_index("ix_price_alerts_active", "price_alerts", ["active"])

    op.create_table(
        "agenda_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("alert_id", sa.Integer(), nullable=True),
        sa.Column("severity", sa.String(8), nullable=False, server_default="info"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_agenda_notifications_user_id", "agenda_notifications", ["user_id"])
    op.create_index("ix_agenda_notifications_created_at", "agenda_notifications", ["created_at"])


def downgrade() -> None:
    op.drop_table("agenda_notifications")
    op.drop_table("price_alerts")
