"""Planetary-interaction colonies (Tracking → PI).

Adds esi_planets — one row per character's active PI colony, replaced each ESI sync.
Stores the list-endpoint facts (planet_type / upgrade_level / num_pins) plus the derived
extraction + storage state (services/pi.py) and per-colony notification latches so the
"extraction stopped / storage full / expiring soon" Agenda notifications fire once per
state change.

Revision ID: 0036_esi_planets
Revises: 0035_reprocessing_preset_structure
Create Date: 2026-06-26
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0036_esi_planets"
down_revision = "0035_reprocessing_preset_structure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "esi_planets" not in set(insp.get_table_names()):
        op.create_table(
            "esi_planets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("character_id", sa.Integer(), nullable=False),
            sa.Column("planet_id", sa.BigInteger(), nullable=False),
            sa.Column("solar_system_id", sa.Integer(), nullable=True),
            sa.Column("planet_type", sa.String(length=20), nullable=True),
            sa.Column("upgrade_level", sa.Integer(), nullable=True),
            sa.Column("num_pins", sa.Integer(), nullable=True),
            sa.Column("last_update", sa.DateTime(), nullable=True),
            sa.Column("has_extractor", sa.Boolean(), nullable=True),
            sa.Column("extracting", sa.Boolean(), nullable=True),
            sa.Column("extractor_expiry", sa.DateTime(), nullable=True),
            sa.Column("products", sa.JSON(), nullable=True),
            sa.Column("storage_used", sa.Float(), nullable=True),
            sa.Column("storage_capacity", sa.Float(), nullable=True),
            sa.Column("synced_at", sa.DateTime(), nullable=True),
            sa.Column("notified_stopped", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("notified_full", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("notified_expiring", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.UniqueConstraint("character_id", "planet_id", name="uq_esi_planet"),
        )
        op.create_index("ix_esi_planets_character_id", "esi_planets", ["character_id"])


def downgrade() -> None:
    op.drop_index("ix_esi_planets_character_id", table_name="esi_planets")
    op.drop_table("esi_planets")
