"""Add esi_standings table (character selection: standings-based broker fee)

Revision ID: 0007_esi_standings
Revises: 0006_esi_characters
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_esi_standings"
down_revision = "0006_esi_characters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "esi_standings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("from_id", sa.Integer(), nullable=False),
        sa.Column("from_type", sa.String(20), nullable=True),
        sa.Column("standing", sa.Float(), nullable=True),
        sa.UniqueConstraint("character_id", "from_id", name="uq_esi_standing"),
    )
    op.create_index("ix_esi_standings_character_id", "esi_standings", ["character_id"])


def downgrade() -> None:
    op.drop_table("esi_standings")
