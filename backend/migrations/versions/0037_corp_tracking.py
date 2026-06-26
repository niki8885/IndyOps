"""Per-corp tracking preference + corp-roster opt-in (Corporations feature, Phase A).

Adds corp_tracking_prefs (per-user toggle for whether an EVE corporation's characters feed
that user's tracking aggregate) and linked_characters.corp_roster_visible (opt-in presence in
the corp activity roster). Also indexes linked_characters.corporation_id, which the
corp-membership derivation queries on every org request.

Revision ID: 0037_corp_tracking
Revises: 0036_esi_planets
Create Date: 2026-06-26
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0037_corp_tracking"
down_revision = "0036_esi_planets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "corp_tracking_prefs" not in tables:
        op.create_table(
            "corp_tracking_prefs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("corporation_id", sa.Integer(), nullable=False),
            sa.Column("tracked", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("user_id", "corporation_id", name="uq_corp_tracking_pref"),
        )
        op.create_index("ix_corp_tracking_prefs_user_id", "corp_tracking_prefs", ["user_id"])

    cols = {c["name"] for c in insp.get_columns("linked_characters")}
    if "corp_roster_visible" not in cols:
        op.add_column("linked_characters",
                      sa.Column("corp_roster_visible", sa.Boolean(), nullable=False, server_default=sa.false()))

    idx = {i["name"] for i in insp.get_indexes("linked_characters")}
    if "ix_linked_characters_corporation_id" not in idx:
        op.create_index("ix_linked_characters_corporation_id", "linked_characters", ["corporation_id"])


def downgrade() -> None:
    op.drop_index("ix_linked_characters_corporation_id", table_name="linked_characters")
    op.drop_column("linked_characters", "corp_roster_visible")
    op.drop_index("ix_corp_tracking_prefs_user_id", table_name="corp_tracking_prefs")
    op.drop_table("corp_tracking_prefs")
