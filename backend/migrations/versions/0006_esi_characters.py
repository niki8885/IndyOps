"""Add linked_characters + esi_* tables (IO-24 ESI integration)

Revision ID: 0006_esi_characters
Revises: 0005_simulation_runs
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_esi_characters"
down_revision = "0005_simulation_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "linked_characters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("character_name", sa.String(200), nullable=False),
        sa.Column("corporation_id", sa.Integer(), nullable=True),
        sa.Column("alliance_id", sa.Integer(), nullable=True),
        sa.Column("owner_hash", sa.String(255), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.Column("access_token_enc", sa.Text(), nullable=True),
        sa.Column("refresh_token_enc", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("wallet_balance", sa.Float(), nullable=True),
        sa.Column("total_sp", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("added_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("character_id", name="uq_linked_character_id"),
    )
    op.create_index("ix_linked_characters_user_id", "linked_characters", ["user_id"])
    op.create_index("ix_linked_characters_character_id", "linked_characters", ["character_id"])

    op.create_table(
        "esi_wallet_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.BigInteger(), nullable=False),
        sa.Column("date", sa.DateTime(), nullable=True),
        sa.Column("type_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.BigInteger(), nullable=True),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("is_buy", sa.Boolean(), nullable=True),
        sa.Column("is_personal", sa.Boolean(), nullable=True),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("location_id", sa.BigInteger(), nullable=True),
        sa.Column("journal_ref_id", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("character_id", "transaction_id", name="uq_esi_tx"),
    )
    op.create_index("ix_esi_wallet_transactions_character_id", "esi_wallet_transactions", ["character_id"])

    op.create_table(
        "esi_skills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("skillpoints", sa.BigInteger(), nullable=True),
        sa.Column("trained_level", sa.Integer(), nullable=True),
        sa.Column("active_level", sa.Integer(), nullable=True),
        sa.UniqueConstraint("character_id", "skill_id", name="uq_esi_skill"),
    )
    op.create_index("ix_esi_skills_character_id", "esi_skills", ["character_id"])

    op.create_table(
        "esi_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("type_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.BigInteger(), nullable=True),
        sa.Column("location_id", sa.BigInteger(), nullable=True),
        sa.Column("location_flag", sa.String(60), nullable=True),
        sa.Column("location_type", sa.String(30), nullable=True),
        sa.Column("is_singleton", sa.Boolean(), nullable=True),
        sa.Column("is_blueprint_copy", sa.Boolean(), nullable=True),
        sa.UniqueConstraint("character_id", "item_id", name="uq_esi_asset"),
    )
    op.create_index("ix_esi_assets_character_id", "esi_assets", ["character_id"])

    op.create_table(
        "esi_contracts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("contract_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(30), nullable=True),
        sa.Column("status", sa.String(30), nullable=True),
        sa.Column("for_corp", sa.Boolean(), nullable=True),
        sa.Column("issuer_id", sa.Integer(), nullable=True),
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
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("availability", sa.String(30), nullable=True),
        sa.Column("start_location_id", sa.BigInteger(), nullable=True),
        sa.Column("end_location_id", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("character_id", "contract_id", name="uq_esi_contract"),
    )
    op.create_index("ix_esi_contracts_character_id", "esi_contracts", ["character_id"])

    op.create_table(
        "esi_industry_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_id", sa.Integer(), nullable=True),
        sa.Column("blueprint_type_id", sa.Integer(), nullable=True),
        sa.Column("blueprint_id", sa.BigInteger(), nullable=True),
        sa.Column("product_type_id", sa.Integer(), nullable=True),
        sa.Column("runs", sa.Integer(), nullable=True),
        sa.Column("licensed_runs", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(30), nullable=True),
        sa.Column("start_date", sa.DateTime(), nullable=True),
        sa.Column("end_date", sa.DateTime(), nullable=True),
        sa.Column("facility_id", sa.BigInteger(), nullable=True),
        sa.Column("station_id", sa.BigInteger(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("probability", sa.Float(), nullable=True),
        sa.UniqueConstraint("character_id", "job_id", name="uq_esi_job"),
    )
    op.create_index("ix_esi_industry_jobs_character_id", "esi_industry_jobs", ["character_id"])


def downgrade() -> None:
    op.drop_table("esi_industry_jobs")
    op.drop_table("esi_contracts")
    op.drop_table("esi_assets")
    op.drop_table("esi_skills")
    op.drop_table("esi_wallet_transactions")
    op.drop_table("linked_characters")
