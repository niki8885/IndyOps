"""Character page overview — location/ship/online + implants + wealth history

Revision ID: 0013_character_overview
Revises: 0012_esi_structures
Create Date: 2026-06-18

Adds the per-character overview data: corp/alliance names, current location /
ship / online + last_login columns and latest assets value on linked_characters,
an esi_implants table (active implants) and a character_wealth_snapshots history
table (liquid + ESI-average-priced assets, one row per sync) for the wealth plot.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_character_overview"
down_revision = "0012_esi_structures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("linked_characters") as b:
        b.add_column(sa.Column("corporation_name", sa.String(200), nullable=True))
        b.add_column(sa.Column("alliance_name", sa.String(200), nullable=True))
        b.add_column(sa.Column("assets_value", sa.Float(), nullable=True))
        b.add_column(sa.Column("location_system_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("location_id", sa.BigInteger(), nullable=True))
        b.add_column(sa.Column("location_type", sa.String(20), nullable=True))
        b.add_column(sa.Column("ship_type_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("ship_name", sa.String(200), nullable=True))
        b.add_column(sa.Column("online", sa.Boolean(), nullable=True))
        b.add_column(sa.Column("last_login", sa.DateTime(), nullable=True))

    op.create_table(
        "esi_implants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("type_id", sa.Integer(), nullable=False),
        sa.UniqueConstraint("character_id", "type_id", name="uq_esi_implant"),
    )
    op.create_index("ix_esi_implants_character_id", "esi_implants", ["character_id"])

    op.create_table(
        "character_wealth_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("liquid", sa.Float(), nullable=True),
        sa.Column("assets_value", sa.Float(), nullable=True),
        sa.Column("total", sa.Float(), nullable=True),
    )
    op.create_index("ix_character_wealth_snapshots_character_id", "character_wealth_snapshots", ["character_id"])
    op.create_index("ix_character_wealth_snapshots_timestamp", "character_wealth_snapshots", ["timestamp"])


def downgrade() -> None:
    op.drop_table("character_wealth_snapshots")
    op.drop_table("esi_implants")
    with op.batch_alter_table("linked_characters") as b:
        for col in ("last_login", "online", "ship_name", "ship_type_id", "location_type",
                    "location_id", "location_system_id", "assets_value",
                    "alliance_name", "corporation_name"):
            b.drop_column(col)
