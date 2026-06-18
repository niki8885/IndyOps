"""Mining journal — ledger + per-character settings + tax write-offs

Revision ID: 0014_mining_journal
Revises: 0013_character_overview
Create Date: 2026-06-18

Backs the per-character mining journal / profit report: the mining ledger
(upserted each sync so month/quarter/year accumulate beyond ESI's ~30-day
window), the editable journal settings (mining tax %, price basis, refine base
yield), and persisted tax write-off records (the "Списать налог" button).
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_mining_journal"
down_revision = "0013_character_overview"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "esi_mining_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("type_id", sa.Integer(), nullable=False),
        sa.Column("solar_system_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("character_id", "date", "type_id", "solar_system_id", name="uq_mining_entry"),
    )
    op.create_index("ix_esi_mining_ledger_character_id", "esi_mining_ledger", ["character_id"])
    op.create_index("ix_esi_mining_ledger_date", "esi_mining_ledger", ["date"])

    op.create_table(
        "character_settings",
        sa.Column("character_id", sa.Integer(), primary_key=True),
        sa.Column("mining_tax_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("price_basis", sa.String(10), nullable=False, server_default="sell"),
        sa.Column("refine_base_yield", sa.Float(), nullable=False, server_default="0.5"),
    )

    op.create_table(
        "mining_tax_writeoffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=True),
        sa.Column("scope", sa.String(12), nullable=False),
        sa.Column("period_type", sa.String(8), nullable=False),
        sa.Column("period_key", sa.String(16), nullable=False),
        sa.Column("gross_value", sa.Float(), nullable=True),
        sa.Column("tax_pct", sa.Float(), nullable=True),
        sa.Column("tax_amount", sa.Float(), nullable=True),
        sa.Column("net_value", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "scope", "character_id", "period_type", "period_key",
                            name="uq_mining_writeoff"),
    )
    op.create_index("ix_mining_tax_writeoffs_user_id", "mining_tax_writeoffs", ["user_id"])


def downgrade() -> None:
    op.drop_table("mining_tax_writeoffs")
    op.drop_table("character_settings")
    op.drop_table("esi_mining_ledger")
