"""Add blueprints table

Revision ID: 0004_blueprints
Revises: 0003_org_public_members
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_blueprints"
down_revision = "0003_org_public_members"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "blueprints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id"), nullable=True),
        sa.Column("blueprint_type_id", sa.Integer(), nullable=False),
        sa.Column("product_type_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("is_bpo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("me", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("te", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runs", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("facility_id", sa.Integer(), sa.ForeignKey("facilities.id"), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_blueprints_user_id", "blueprints", ["user_id"])
    op.create_index("ix_blueprints_organisation_id", "blueprints", ["organisation_id"])
    op.create_index("ix_blueprints_blueprint_type_id", "blueprints", ["blueprint_type_id"])
    op.create_index("ix_blueprints_product_type_id", "blueprints", ["product_type_id"])


def downgrade() -> None:
    op.drop_table("blueprints")
