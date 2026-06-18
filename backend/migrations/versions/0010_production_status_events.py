"""Add production_status_events (PAK job status history / tracking)

Revision ID: 0010_production_status_events
Revises: 0009_delivery_status_events
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_production_status_events"
down_revision = "0009_delivery_status_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "production_status_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("production_jobs.id"), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_production_status_events_job_id", "production_status_events", ["job_id"])
    op.create_index("ix_production_status_events_at", "production_status_events", ["at"])


def downgrade() -> None:
    op.drop_index("ix_production_status_events_at", table_name="production_status_events")
    op.drop_index("ix_production_status_events_job_id", table_name="production_status_events")
    op.drop_table("production_status_events")
