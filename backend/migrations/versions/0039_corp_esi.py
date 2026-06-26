"""Corporation ESI (Phase B) — real corp-level wallet / industry / members.

Adds linked_characters.corp_roles (the character's in-game corp roles, which gate the
corp-level ESI sync) and three corp-keyed tables populated by a role-holding character:
  - esi_corp_wallets        — wallet division balances (real corp capital)
  - esi_corp_industry_jobs  — corp-OWNED industry jobs (distinct from members' personal jobs)
  - esi_corp_members        — the real in-game roster

These let the Corporations dashboard show the actual corporation instead of re-grouping the
requesting user's own characters, and stop attributing personal work to the corp.

Revision ID: 0039_corp_esi
Revises: 0038_job_notify
Create Date: 2026-06-27
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0039_corp_esi"
down_revision = "0038_job_notify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    tables = set(insp.get_table_names())

    cols = {c["name"] for c in insp.get_columns("linked_characters")}
    if "corp_roles" not in cols:
        op.add_column("linked_characters", sa.Column("corp_roles", sa.JSON(), nullable=True))

    if "esi_corp_wallets" not in tables:
        op.create_table(
            "esi_corp_wallets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("corporation_id", sa.Integer(), nullable=False),
            sa.Column("division", sa.Integer(), nullable=False),
            sa.Column("balance", sa.Float(), nullable=True),
            sa.Column("synced_by", sa.Integer(), nullable=True),
            sa.Column("synced_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("corporation_id", "division", name="uq_corp_wallet"),
        )
        op.create_index("ix_esi_corp_wallets_corporation_id", "esi_corp_wallets", ["corporation_id"])

    if "esi_corp_industry_jobs" not in tables:
        op.create_table(
            "esi_corp_industry_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("corporation_id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.BigInteger(), nullable=False),
            sa.Column("installer_id", sa.Integer(), nullable=True),
            sa.Column("activity_id", sa.Integer(), nullable=True),
            sa.Column("blueprint_type_id", sa.Integer(), nullable=True),
            sa.Column("product_type_id", sa.Integer(), nullable=True),
            sa.Column("runs", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=True),
            sa.Column("start_date", sa.DateTime(), nullable=True),
            sa.Column("end_date", sa.DateTime(), nullable=True),
            sa.Column("location_id", sa.BigInteger(), nullable=True),
            sa.Column("cost", sa.Float(), nullable=True),
            sa.Column("synced_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("corporation_id", "job_id", name="uq_corp_job"),
        )
        op.create_index("ix_esi_corp_industry_jobs_corporation_id", "esi_corp_industry_jobs", ["corporation_id"])

    if "esi_corp_members" not in tables:
        op.create_table(
            "esi_corp_members",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("corporation_id", sa.Integer(), nullable=False),
            sa.Column("character_id", sa.Integer(), nullable=False),
            sa.Column("character_name", sa.String(length=200), nullable=True),
            sa.Column("synced_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("corporation_id", "character_id", name="uq_corp_member"),
        )
        op.create_index("ix_esi_corp_members_corporation_id", "esi_corp_members", ["corporation_id"])


def downgrade() -> None:
    op.drop_index("ix_esi_corp_members_corporation_id", table_name="esi_corp_members")
    op.drop_table("esi_corp_members")
    op.drop_index("ix_esi_corp_industry_jobs_corporation_id", table_name="esi_corp_industry_jobs")
    op.drop_table("esi_corp_industry_jobs")
    op.drop_index("ix_esi_corp_wallets_corporation_id", table_name="esi_corp_wallets")
    op.drop_table("esi_corp_wallets")
    op.drop_column("linked_characters", "corp_roles")
