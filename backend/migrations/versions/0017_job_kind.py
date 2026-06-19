"""Production jobs — kind discriminator (pak | indy)

Revision ID: 0017_job_kind
Revises: 0016_character_flags
Create Date: 2026-06-19

Splits production_jobs into outsourced PAK contracts (``kind='pak'``, the existing
rows) and internal planned IndyJobs (``kind='indy'``, Calculator → "Add to plan").
Existing rows default to 'pak'.
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_job_kind"
down_revision = "0016_character_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("production_jobs",
                  sa.Column("kind", sa.String(8), nullable=False, server_default="pak"))
    op.create_index("ix_production_jobs_kind", "production_jobs", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_production_jobs_kind", table_name="production_jobs")
    op.drop_column("production_jobs", "kind")
