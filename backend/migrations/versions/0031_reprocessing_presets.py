"""Ore reprocessing — saved presets + an inventory source marker.

Adds:
  * reprocessing_presets — a user's named reprocessing setup (base yield, yield rigs,
    facility tax, reprocessing skills/implant) so warehouse ore can be refined at a saved
    location without re-entering rig %/tax each time.
  * inventory.source — marks how a lot entered the warehouse. "reprocess" lots (minerals
    refined from your own ore) are fed into the Tracking → Industry FIFO cost ledger so
    own-ore builds get a cost basis instead of reading "missing inputs".

Revision ID: 0031_reprocessing_presets
Revises: 0030_tracking_income
Create Date: 2026-06-25
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0031_reprocessing_presets"
down_revision = "0030_tracking_income"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "reprocessing_presets" not in tables:
        op.create_table(
            "reprocessing_presets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("base_yield", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("tax_pct", sa.Float(), nullable=False, server_default="0"),
            sa.Column("security", sa.String(4), nullable=False, server_default="hi"),
            sa.Column("reprocessing_lvl", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("efficiency_lvl", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ore_specific_lvl", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("implant_pct", sa.Float(), nullable=False, server_default="0"),
            sa.Column("rig_type_ids", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_reprocessing_presets_user_id", "reprocessing_presets", ["user_id"])

    cols = {c["name"] for c in insp.get_columns("inventory")} if "inventory" in tables else set()
    if "inventory" in tables and "source" not in cols:
        op.add_column("inventory", sa.Column("source", sa.String(20), nullable=True))


def downgrade() -> None:
    insp = inspect(op.get_bind())
    if "inventory" in set(insp.get_table_names()):
        cols = {c["name"] for c in insp.get_columns("inventory")}
        if "source" in cols:
            op.drop_column("inventory", "source")
    op.drop_index("ix_reprocessing_presets_user_id", table_name="reprocessing_presets")
    op.drop_table("reprocessing_presets")
