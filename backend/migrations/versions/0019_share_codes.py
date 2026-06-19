"""Add share_codes table (short shareable calculator/chain job codes)

Revision ID: 0019_share_codes
Revises: 0018_scenario_analyses
Create Date: 2026-06-19
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0019_share_codes"
down_revision = "0018_scenario_analyses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "share_codes" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "share_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("source", sa.String(12), nullable=False, server_default="production"),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_share_codes_code", "share_codes", ["code"], unique=True)
    op.create_index("ix_share_codes_created_at", "share_codes", ["created_at"])
    op.create_index("ix_share_codes_expires_at", "share_codes", ["expires_at"])


def downgrade() -> None:
    op.drop_table("share_codes")
