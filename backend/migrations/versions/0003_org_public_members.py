"""Add is_public to organisations + organisation_members table

Revision ID: 0003_org_public_members
Revises: 0002_facilitytype_uppercase
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_org_public_members"
down_revision = "0002_facilitytype_uppercase"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organisations",
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_table(
        "organisation_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="JUNIOR"),
        sa.Column("joined_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("org_id", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("organisation_members")
    op.drop_column("organisations", "is_public")
