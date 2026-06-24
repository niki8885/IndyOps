"""Add bank_ledger_entries table (Aureus/Penny in-app currency credits)

Each row is a credit to a user's in-app balance from an in-game ISK donation to the
bank corporation, detected from the wallet journal (ref_type 'player_donation').
Append-only and idempotent on the journal entry id (ref_id). Amounts are kept in
integer Penny (1 ISK = 100 Penny) so balances sum exactly.

Revision ID: 0029_bank_ledger
Revises: 0028_esi_market_orders
Create Date: 2026-06-24
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0029_bank_ledger"
down_revision = "0028_esi_market_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "bank_ledger_entries" not in insp.get_table_names():
        op.create_table(
            "bank_ledger_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("character_id", sa.Integer(), nullable=True),
            sa.Column("ref_id", sa.BigInteger(), nullable=False),
            sa.Column("amount_penny", sa.BigInteger(), nullable=False),
            sa.Column("amount_isk", sa.Float(), nullable=True),
            sa.Column("date", sa.DateTime(), nullable=True),
            sa.Column("description", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("ref_id", name="uq_bank_ledger_ref"),
        )
        op.create_index("ix_bank_ledger_entries_user_id", "bank_ledger_entries", ["user_id"])
        op.create_index("ix_bank_ledger_entries_character_id", "bank_ledger_entries", ["character_id"])


def downgrade() -> None:
    op.drop_index("ix_bank_ledger_entries_character_id", table_name="bank_ledger_entries")
    op.drop_index("ix_bank_ledger_entries_user_id", table_name="bank_ledger_entries")
    op.drop_table("bank_ledger_entries")
