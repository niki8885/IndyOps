"""Production jobs — kind discriminator (pak | indy)

Revision ID: 0017_job_kind
Revises: 0016_character_flags
Create Date: 2026-06-19

Splits production_jobs into outsourced PAK contracts (``kind='pak'``, the existing
rows) and internal planned IndyJobs (``kind='indy'``, Calculator → "Add to plan").
Existing rows default to 'pak'.

Idempotent (add-column / create-index only if missing) so re-runs converge.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0017_job_kind"
down_revision = "0016_character_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("production_jobs")}
    if "kind" not in cols:
        op.add_column("production_jobs",
                      sa.Column("kind", sa.String(8), nullable=False, server_default="pak"))
    idx = {i["name"] for i in insp.get_indexes("production_jobs")}
    if "ix_production_jobs_kind" not in idx:
        op.create_index("ix_production_jobs_kind", "production_jobs", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_production_jobs_kind", table_name="production_jobs")
    op.drop_column("production_jobs", "kind")
