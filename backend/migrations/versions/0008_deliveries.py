"""Add deliveries table + inventory.delivery_id (Inventory → Delivery feature)

Revision ID: 0008_deliveries
Revises: 0007_esi_standings
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_deliveries"
down_revision = "0007_esi_standings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("source_place", sa.String(200), nullable=True),
        sa.Column("source_system", sa.String(200), nullable=True),
        sa.Column("target_system", sa.String(200), nullable=True),
        sa.Column("target_place", sa.String(200), nullable=True),
        sa.Column("mode", sa.String(10), nullable=False, server_default="regular"),
        sa.Column("sender_character", sa.String(200), nullable=True),
        sa.Column("sender_employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("jumps", sa.Integer(), nullable=True),
        sa.Column("isk_per_jump_m3", sa.Float(), nullable=True),
        sa.Column("jf_ship", sa.String(40), nullable=True),
        sa.Column("isotope_name", sa.String(60), nullable=True),
        sa.Column("isotope_type_id", sa.Integer(), nullable=True),
        sa.Column("light_years", sa.Float(), nullable=True),
        sa.Column("isotopes_per_ly", sa.Float(), nullable=True),
        sa.Column("trips", sa.Integer(), nullable=True),
        sa.Column("round_trip", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("isotope_price", sa.Float(), nullable=True),
        sa.Column("total_isotopes", sa.BigInteger(), nullable=True),
        sa.Column("total_volume", sa.Float(), nullable=True),
        sa.Column("total_value", sa.Float(), nullable=True),
        sa.Column("est_cost", sa.Float(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("items_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_deliveries_user_id", "deliveries", ["user_id"])
    op.create_index("ix_deliveries_project_id", "deliveries", ["project_id"])
    op.create_index("ix_deliveries_status", "deliveries", ["status"])
    op.create_index("ix_deliveries_code", "deliveries", ["code"])

    op.add_column("inventory", sa.Column("delivery_id", sa.Integer(),
                                         sa.ForeignKey("deliveries.id"), nullable=True))
    op.create_index("ix_inventory_delivery_id", "inventory", ["delivery_id"])


def downgrade() -> None:
    op.drop_index("ix_inventory_delivery_id", table_name="inventory")
    op.drop_column("inventory", "delivery_id")
    op.drop_table("deliveries")
