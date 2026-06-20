"""Add haul_candidates (Jita → C-J6MT auto haul scanner)

Revision ID: 0023_haul_candidates
Revises: 0022_system_cost_indices
Create Date: 2026-06-20

Current-state upsert table (replaced each scanner run) — like the trade optimizer
tables (0011), NOT a Timescale hypertable.
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_haul_candidates"
down_revision = "0022_system_cost_indices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "haul_candidates",
        sa.Column("item_id", sa.Integer(), primary_key=True),
        sa.Column("type_name", sa.String(200), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("jita_buy", sa.Float(), nullable=True),
        sa.Column("jita_sell", sa.Float(), nullable=True),
        sa.Column("cj_buy", sa.Float(), nullable=True),
        sa.Column("cj_sell", sa.Float(), nullable=True),
        sa.Column("item_volume_m3", sa.Float(), nullable=True),
        sa.Column("daily_volume", sa.Float(), nullable=True),
        sa.Column("best_method", sa.String(12), nullable=True),
        sa.Column("profit_per_unit", sa.Float(), nullable=True),
        sa.Column("margin_pct", sa.Float(), nullable=True),
        sa.Column("transport_per_unit", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_haul_candidates_updated_at", "haul_candidates", ["updated_at"])
    op.create_index("ix_haul_candidates_margin", "haul_candidates", ["margin_pct"])


def downgrade() -> None:
    op.drop_index("ix_haul_candidates_margin", table_name="haul_candidates")
    op.drop_index("ix_haul_candidates_updated_at", table_name="haul_candidates")
    op.drop_table("haul_candidates")
