"""Add jita_buy_volume to haul_candidates (stagnation filter — Jita buy-order depth)

Revision ID: 0026_haul_jita_buy_volume
Revises: 0025_visibility_follow
Create Date: 2026-06-22

The haul scanner now records how many units sit in standing Jita BUY orders for each
candidate (from the Fuzzwork aggregate), so the UI can offer an optional "minimum Jita
buy depth" filter to skip items with no real demand (avoid hauling into a stale market).
No backfill needed — haul_candidates is fully replaced each scanner run.
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_haul_jita_buy_volume"
down_revision = "0025_visibility_follow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("haul_candidates", sa.Column("jita_buy_volume", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("haul_candidates", "jita_buy_volume")
