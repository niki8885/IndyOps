"""Add esi_structures — cached Upwell structure name resolution (asset locations)

Revision ID: 0012_esi_structures
Revises: 0011_trade_candidates
Create Date: 2026-06-18

Player structure ids in assets only resolve to a name via ESI
/universe/structures/{id}/ (needs the read_structures scope + docking access).
This caches the result globally so it's fetched once and reused, with an
``error`` column to back off on 403/404 rather than re-hammering.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_esi_structures"
down_revision = "0011_trade_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "esi_structures",
        sa.Column("structure_id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("solar_system_id", sa.Integer(), nullable=True),
        sa.Column("type_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(20), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("esi_structures")
