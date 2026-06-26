"""Structure type on reprocessing presets.

Adds reprocessing_presets.structure_type so a preset records which structure it models
(NPC station / Athanor / Tatara); the editor uses it to fill the base yield for an
accurate refine, instead of asking the user to type the base yield by hand.

Revision ID: 0035_reprocessing_preset_structure
Revises: 0034_tracking_exclusions
Create Date: 2026-06-26
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0035_reprocessing_preset_structure"
down_revision = "0034_tracking_exclusions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("reprocessing_presets")}
    if "structure_type" not in cols:
        op.add_column("reprocessing_presets", sa.Column("structure_type", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("reprocessing_presets", "structure_type")
