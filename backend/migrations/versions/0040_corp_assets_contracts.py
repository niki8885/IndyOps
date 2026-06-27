"""Corporation ESI Phase C — corp assets (warehouses), divisions, contracts + items.

Extends Phase B (0039) with corp-keyed tables for the Corporations dashboard's new
Warehouses and Contracts tabs:
  - esi_corp_assets          — corp-owned items (offices / corp hangars / containers)
  - esi_corp_divisions       — hangar/wallet division names (so a warehouse shows "Minerals")
  - esi_corp_contracts       — corp contracts (issued by / to the corporation)
  - esi_corp_contract_items  — their contents (immutable, fetched once)

Populated by a linked character holding the corp scopes + role (assets/divisions need
Director; contracts need only the corp-contracts scope). Re-link once to grant the scopes.

Revision ID: 0040_corp_assets_contracts
Revises: 0039_corp_esi
Create Date: 2026-06-27
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0040_corp_assets_contracts"
down_revision = "0039_corp_esi"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "esi_corp_assets" not in tables:
        op.create_table(
            "esi_corp_assets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("corporation_id", sa.Integer(), nullable=False),
            sa.Column("item_id", sa.BigInteger(), nullable=False),
            sa.Column("type_id", sa.Integer(), nullable=True),
            sa.Column("quantity", sa.BigInteger(), nullable=True),
            sa.Column("location_id", sa.BigInteger(), nullable=True),
            sa.Column("location_flag", sa.String(length=60), nullable=True),
            sa.Column("location_type", sa.String(length=30), nullable=True),
            sa.Column("is_singleton", sa.Boolean(), nullable=True),
            sa.Column("is_blueprint_copy", sa.Boolean(), nullable=True),
            sa.Column("synced_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("corporation_id", "item_id", name="uq_corp_asset"),
        )
        op.create_index("ix_esi_corp_assets_corporation_id", "esi_corp_assets", ["corporation_id"])

    if "esi_corp_divisions" not in tables:
        op.create_table(
            "esi_corp_divisions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("corporation_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(length=10), nullable=False),
            sa.Column("division", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=True),
            sa.Column("synced_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("corporation_id", "kind", "division", name="uq_corp_division"),
        )
        op.create_index("ix_esi_corp_divisions_corporation_id", "esi_corp_divisions", ["corporation_id"])

    if "esi_corp_contracts" not in tables:
        op.create_table(
            "esi_corp_contracts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("corporation_id", sa.Integer(), nullable=False),
            sa.Column("contract_id", sa.BigInteger(), nullable=False),
            sa.Column("type", sa.String(length=30), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=True),
            sa.Column("for_corp", sa.Boolean(), nullable=True),
            sa.Column("issuer_id", sa.Integer(), nullable=True),
            sa.Column("issuer_corporation_id", sa.Integer(), nullable=True),
            sa.Column("assignee_id", sa.Integer(), nullable=True),
            sa.Column("acceptor_id", sa.Integer(), nullable=True),
            sa.Column("date_issued", sa.DateTime(), nullable=True),
            sa.Column("date_expired", sa.DateTime(), nullable=True),
            sa.Column("date_accepted", sa.DateTime(), nullable=True),
            sa.Column("date_completed", sa.DateTime(), nullable=True),
            sa.Column("price", sa.Float(), nullable=True),
            sa.Column("reward", sa.Float(), nullable=True),
            sa.Column("collateral", sa.Float(), nullable=True),
            sa.Column("volume", sa.Float(), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.Column("availability", sa.String(length=30), nullable=True),
            sa.Column("start_location_id", sa.BigInteger(), nullable=True),
            sa.Column("end_location_id", sa.BigInteger(), nullable=True),
            sa.Column("synced_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("corporation_id", "contract_id", name="uq_corp_contract"),
        )
        op.create_index("ix_esi_corp_contracts_corporation_id", "esi_corp_contracts", ["corporation_id"])

    if "esi_corp_contract_items" not in tables:
        op.create_table(
            "esi_corp_contract_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("corporation_id", sa.Integer(), nullable=False),
            sa.Column("contract_id", sa.BigInteger(), nullable=False),
            sa.Column("record_id", sa.BigInteger(), nullable=False),
            sa.Column("type_id", sa.Integer(), nullable=True),
            sa.Column("quantity", sa.BigInteger(), nullable=True),
            sa.Column("is_included", sa.Boolean(), nullable=True),
            sa.Column("is_singleton", sa.Boolean(), nullable=True),
            sa.UniqueConstraint("corporation_id", "contract_id", "record_id", name="uq_corp_contract_item"),
        )
        op.create_index("ix_esi_corp_contract_items_corporation_id", "esi_corp_contract_items", ["corporation_id"])
        op.create_index("ix_esi_corp_contract_items_contract_id", "esi_corp_contract_items", ["contract_id"])


def downgrade() -> None:
    op.drop_index("ix_esi_corp_contract_items_contract_id", table_name="esi_corp_contract_items")
    op.drop_index("ix_esi_corp_contract_items_corporation_id", table_name="esi_corp_contract_items")
    op.drop_table("esi_corp_contract_items")
    op.drop_index("ix_esi_corp_contracts_corporation_id", table_name="esi_corp_contracts")
    op.drop_table("esi_corp_contracts")
    op.drop_index("ix_esi_corp_divisions_corporation_id", table_name="esi_corp_divisions")
    op.drop_table("esi_corp_divisions")
    op.drop_index("ix_esi_corp_assets_corporation_id", table_name="esi_corp_assets")
    op.drop_table("esi_corp_assets")
