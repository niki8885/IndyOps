"""Add group_id + meta_group_id to haul_candidates (Drugs/group + T1/T2/Faction filtering)

Revision ID: 0024_haul_meta_groups
Revises: 0023_haul_candidates
Create Date: 2026-06-21

The haul scanner now gates by SDE group (boosters / "Drugs") in addition to category
and tags each candidate with its tech-level meta group (1 T1 · 2 T2 · 4 Faction; NULL
⇒ Tech I). No backfill needed — haul_candidates is fully replaced each scanner run.
"""
from alembic import op
import sqlalchemy as sa

revision = "0024_haul_meta_groups"
down_revision = "0023_haul_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("haul_candidates", sa.Column("group_id", sa.Integer(), nullable=True))
    op.add_column("haul_candidates", sa.Column("meta_group_id", sa.Integer(), nullable=True))
    op.create_index("ix_haul_candidates_meta", "haul_candidates", ["meta_group_id"])


def downgrade() -> None:
    op.drop_index("ix_haul_candidates_meta", table_name="haul_candidates")
    op.drop_column("haul_candidates", "meta_group_id")
    op.drop_column("haul_candidates", "group_id")
