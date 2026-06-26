"""Industry-job completion notifications (Tracking).

Adds esi_industry_jobs.notified_ready — a per-job latch so the "job finished, not collected"
Agenda notification fires once when ESI flips the job's status to 'ready', and is withdrawn
when it flips to 'delivered' (self-dismiss on collect). Also adds agenda_notifications.source_key,
an optional source tag (e.g. 'job_ready:<job_id>') the producing sync uses to find and delete
its own auto-managed notification when the condition clears.

Revision ID: 0038_job_notify
Revises: 0037_corp_tracking
Create Date: 2026-06-27
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0038_job_notify"
down_revision = "0037_corp_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())

    job_cols = {c["name"] for c in insp.get_columns("esi_industry_jobs")}
    if "notified_ready" not in job_cols:
        op.add_column("esi_industry_jobs",
                      sa.Column("notified_ready", sa.Boolean(), nullable=False, server_default=sa.false()))

    note_cols = {c["name"] for c in insp.get_columns("agenda_notifications")}
    if "source_key" not in note_cols:
        op.add_column("agenda_notifications", sa.Column("source_key", sa.String(length=60), nullable=True))
    idx = {i["name"] for i in insp.get_indexes("agenda_notifications")}
    if "ix_agenda_notifications_source_key" not in idx:
        op.create_index("ix_agenda_notifications_source_key", "agenda_notifications", ["source_key"])


def downgrade() -> None:
    op.drop_index("ix_agenda_notifications_source_key", table_name="agenda_notifications")
    op.drop_column("agenda_notifications", "source_key")
    op.drop_column("esi_industry_jobs", "notified_ready")
