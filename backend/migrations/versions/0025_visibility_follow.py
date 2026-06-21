"""Add visibility (private/public/group) to facilities + organisations, and watch-list
follow tables (facility_follows, organisation_follows).

Revision ID: 0025_visibility_follow
Revises: 0024_haul_meta_groups
Create Date: 2026-06-21

Public facilities/orgs can be followed (a personal watch list, separate from org
membership) and — for facilities — used in the follower's own calculations.
"""
from alembic import op
import sqlalchemy as sa

revision = "0025_visibility_follow"
down_revision = "0024_haul_meta_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("facilities", sa.Column(
        "visibility", sa.String(10), nullable=False, server_default="private"))
    op.create_index("ix_facilities_visibility", "facilities", ["visibility"])

    op.add_column("organisations", sa.Column(
        "visibility", sa.String(10), nullable=False, server_default="private"))
    # backfill from the legacy boolean so existing public orgs stay public
    op.execute("UPDATE organisations SET visibility = 'public' WHERE is_public = true")

    op.create_table(
        "facility_follows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("facility_id", sa.Integer(),
                  sa.ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "facility_id", name="uq_facility_follow"),
    )
    op.create_index("ix_facility_follows_user_id", "facility_follows", ["user_id"])
    op.create_index("ix_facility_follows_facility_id", "facility_follows", ["facility_id"])

    op.create_table(
        "organisation_follows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", sa.Integer(),
                  sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "org_id", name="uq_org_follow"),
    )
    op.create_index("ix_organisation_follows_user_id", "organisation_follows", ["user_id"])
    op.create_index("ix_organisation_follows_org_id", "organisation_follows", ["org_id"])


def downgrade() -> None:
    op.drop_table("organisation_follows")
    op.drop_table("facility_follows")
    op.drop_index("ix_facilities_visibility", table_name="facilities")
    op.drop_column("organisations", "visibility")
    op.drop_column("facilities", "visibility")
