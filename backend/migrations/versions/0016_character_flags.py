"""Character settings — role/grouping flags

Revision ID: 0016_character_flags
Revises: 0015_agenda_alerts
Create Date: 2026-06-19

Adds the Character Settings tab's criteria to ``character_settings``: a favourite
pin, whether the character counts toward overall capital / the common production
chain, manufacturer / trader role flags, and a free-text custom group.
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_character_flags"
down_revision = "0015_agenda_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("character_settings", sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("character_settings", sa.Column("track_wealth", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("character_settings", sa.Column("track_production", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("character_settings", sa.Column("is_manufacturer", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("character_settings", sa.Column("is_trader", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("character_settings", sa.Column("group_name", sa.String(60), nullable=True))


def downgrade() -> None:
    for col in ("group_name", "is_trader", "is_manufacturer", "track_production", "track_wealth", "favorite"):
        op.drop_column("character_settings", col)
