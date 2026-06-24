"""Tracking income trackers — Deliverly (courier), Mission & Ratting.

Adds the tables backing the new Tracking sub-tabs:
  * esi_wallet_entries  — income wallet-journal entries (mission rewards, bounty, ESS),
                          captured during the ESI sync. Append-only, idempotent on
                          (character_id, ref_id).
  * contract_annotations — per-user tags + note for a courier contract (Deliverly).
  * courier_route_cache  — cached gate-jump count per (start, end) location pair.
  * loot_appraisals      — saved, ISK-valued loot pastes tied to the Ratting tracker.
  * esi_name_cache       — id → name/category cache (mission agents / counterparties).

Revision ID: 0030_tracking_income
Revises: 0029_bank_ledger
Create Date: 2026-06-24
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0030_tracking_income"
down_revision = "0029_bank_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "esi_wallet_entries" not in tables:
        op.create_table(
            "esi_wallet_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("character_id", sa.Integer(), nullable=False),
            sa.Column("ref_id", sa.BigInteger(), nullable=False),
            sa.Column("ref_type", sa.String(40), nullable=True),
            sa.Column("amount", sa.Float(), nullable=True),
            sa.Column("balance", sa.Float(), nullable=True),
            sa.Column("date", sa.DateTime(), nullable=True),
            sa.Column("first_party_id", sa.Integer(), nullable=True),
            sa.Column("second_party_id", sa.Integer(), nullable=True),
            sa.Column("description", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("character_id", "ref_id", name="uq_esi_wallet_entry"),
        )
        op.create_index("ix_esi_wallet_entries_user_id", "esi_wallet_entries", ["user_id"])
        op.create_index("ix_esi_wallet_entries_character_id", "esi_wallet_entries", ["character_id"])
        op.create_index("ix_esi_wallet_entries_ref_type", "esi_wallet_entries", ["ref_type"])
        op.create_index("ix_esi_wallet_entries_date", "esi_wallet_entries", ["date"])

    if "contract_annotations" not in tables:
        op.create_table(
            "contract_annotations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("contract_id", sa.BigInteger(), nullable=False),
            sa.Column("tags", sa.String(255), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("user_id", "contract_id", name="uq_contract_annotation"),
        )
        op.create_index("ix_contract_annotations_user_id", "contract_annotations", ["user_id"])
        op.create_index("ix_contract_annotations_contract_id", "contract_annotations", ["contract_id"])

    if "courier_route_cache" not in tables:
        op.create_table(
            "courier_route_cache",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("start_location_id", sa.BigInteger(), nullable=False),
            sa.Column("end_location_id", sa.BigInteger(), nullable=False),
            sa.Column("start_system_id", sa.Integer(), nullable=True),
            sa.Column("end_system_id", sa.Integer(), nullable=True),
            sa.Column("jumps", sa.Integer(), nullable=True),
            sa.Column("computed_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("start_location_id", "end_location_id", name="uq_courier_route"),
        )

    if "loot_appraisals" not in tables:
        op.create_table(
            "loot_appraisals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("character_id", sa.Integer(), nullable=True),
            sa.Column("date", sa.DateTime(), nullable=True),
            sa.Column("title", sa.String(120), nullable=True),
            sa.Column("tags", sa.String(255), nullable=True),
            sa.Column("raw_text", sa.Text(), nullable=True),
            sa.Column("pricing", sa.String(20), nullable=True),
            sa.Column("value_isk", sa.Float(), nullable=True),
            sa.Column("items_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_loot_appraisals_user_id", "loot_appraisals", ["user_id"])
        op.create_index("ix_loot_appraisals_date", "loot_appraisals", ["date"])

    if "esi_name_cache" not in tables:
        op.create_table(
            "esi_name_cache",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("name", sa.String(255), nullable=True),
            sa.Column("category", sa.String(40), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("esi_name_cache")
    op.drop_index("ix_loot_appraisals_date", table_name="loot_appraisals")
    op.drop_index("ix_loot_appraisals_user_id", table_name="loot_appraisals")
    op.drop_table("loot_appraisals")
    op.drop_table("courier_route_cache")
    op.drop_index("ix_contract_annotations_contract_id", table_name="contract_annotations")
    op.drop_index("ix_contract_annotations_user_id", table_name="contract_annotations")
    op.drop_table("contract_annotations")
    op.drop_index("ix_esi_wallet_entries_date", table_name="esi_wallet_entries")
    op.drop_index("ix_esi_wallet_entries_ref_type", table_name="esi_wallet_entries")
    op.drop_index("ix_esi_wallet_entries_character_id", table_name="esi_wallet_entries")
    op.drop_index("ix_esi_wallet_entries_user_id", table_name="esi_wallet_entries")
    op.drop_table("esi_wallet_entries")
