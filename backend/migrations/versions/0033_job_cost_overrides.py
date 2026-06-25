"""Per-job custom unit-cost overrides (Tracking → Industry job detail panel).

Adds job_cost_overrides: a user's manual unit cost for a job whose inputs couldn't be
attributed to tracked buys ("Custom Unit Price"), so its profit can still be tracked.

Revision ID: 0033_job_cost_overrides
Revises: 0032_contract_items
Create Date: 2026-06-25
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0033_job_cost_overrides"
down_revision = "0032_contract_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "job_cost_overrides" not in set(insp.get_table_names()):
        op.create_table(
            "job_cost_overrides",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("job_id", sa.BigInteger(), nullable=False),
            sa.Column("custom_unit_price", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("user_id", "job_id", name="uq_job_cost_override"),
        )
        op.create_index("ix_job_cost_overrides_user_id", "job_cost_overrides", ["user_id"])
        op.create_index("ix_job_cost_overrides_job_id", "job_cost_overrides", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_job_cost_overrides_job_id", table_name="job_cost_overrides")
    op.drop_index("ix_job_cost_overrides_user_id", table_name="job_cost_overrides")
    op.drop_table("job_cost_overrides")
