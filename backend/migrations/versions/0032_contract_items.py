"""Contract items — item-exchange contract contents for Contract-Profit tracking.

Adds esi_contract_items: the items inside a finished item-exchange contract (fetched once,
immutable), so the Tracking → Industry Contract-Profit view can attribute a realized cost
basis to what was sold via contract.

Revision ID: 0032_contract_items
Revises: 0031_reprocessing_presets
Create Date: 2026-06-25
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0032_contract_items"
down_revision = "0031_reprocessing_presets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "esi_contract_items" not in set(insp.get_table_names()):
        op.create_table(
            "esi_contract_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("character_id", sa.Integer(), nullable=False),
            sa.Column("contract_id", sa.BigInteger(), nullable=False),
            sa.Column("record_id", sa.BigInteger(), nullable=False),
            sa.Column("type_id", sa.Integer(), nullable=True),
            sa.Column("quantity", sa.BigInteger(), nullable=True),
            sa.Column("is_included", sa.Boolean(), nullable=True),
            sa.Column("is_singleton", sa.Boolean(), nullable=True),
            sa.UniqueConstraint("character_id", "contract_id", "record_id", name="uq_esi_contract_item"),
        )
        op.create_index("ix_esi_contract_items_character_id", "esi_contract_items", ["character_id"])
        op.create_index("ix_esi_contract_items_contract_id", "esi_contract_items", ["contract_id"])


def downgrade() -> None:
    op.drop_index("ix_esi_contract_items_contract_id", table_name="esi_contract_items")
    op.drop_index("ix_esi_contract_items_character_id", table_name="esi_contract_items")
    op.drop_table("esi_contract_items")
