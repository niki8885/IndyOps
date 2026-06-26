"""Per-row exclusions for the Tracking → Industry totals.

Adds tracking_exclusions: a user can opt a completed industry job or a sold contract
out of the summary metrics (a mistake, a gift, a test build). Excluded rows still show
in their table but don't count toward the headline numbers. Keyed by (user_id, kind, ref_id).

Revision ID: 0034_tracking_exclusions
Revises: 0033_job_cost_overrides
Create Date: 2026-06-26
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0034_tracking_exclusions"
down_revision = "0033_job_cost_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "tracking_exclusions" not in set(insp.get_table_names()):
        op.create_table(
            "tracking_exclusions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("ref_id", sa.BigInteger(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("user_id", "kind", "ref_id", name="uq_tracking_exclusion"),
        )
        op.create_index("ix_tracking_exclusions_user_id", "tracking_exclusions", ["user_id"])
        op.create_index("ix_tracking_exclusions_ref_id", "tracking_exclusions", ["ref_id"])


def downgrade() -> None:
    op.drop_index("ix_tracking_exclusions_ref_id", table_name="tracking_exclusions")
    op.drop_index("ix_tracking_exclusions_user_id", table_name="tracking_exclusions")
    op.drop_table("tracking_exclusions")
