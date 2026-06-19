"""Add esi_blueprints table (character-owned BPOs/BPCs with ME/TE/runs)

Revision ID: 0021_esi_blueprints
Revises: 0020_quiz_results
Create Date: 2026-06-19
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0021_esi_blueprints"
down_revision = "0020_quiz_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "esi_blueprints" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "esi_blueprints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("type_id", sa.Integer(), nullable=True),
        sa.Column("material_efficiency", sa.Integer(), nullable=True),
        sa.Column("time_efficiency", sa.Integer(), nullable=True),
        sa.Column("runs", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("location_id", sa.BigInteger(), nullable=True),
        sa.Column("location_flag", sa.String(60), nullable=True),
        sa.UniqueConstraint("character_id", "item_id", name="uq_esi_blueprint"),
    )
    op.create_index("ix_esi_blueprints_character_id", "esi_blueprints", ["character_id"])


def downgrade() -> None:
    op.drop_table("esi_blueprints")
