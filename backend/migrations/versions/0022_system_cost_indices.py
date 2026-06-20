"""Persisted ESI system cost indices + Facility.solar_system_id

Adds a ``system_cost_indices`` table (one row per solar system per industry
activity, refreshed by the worker) and a ``solar_system_id`` column on
``facilities`` so research/copy/invention job costs can look up the correct
per-activity index for a factory's system.

Revision ID: 0022_system_cost_indices
Revises: 0021_esi_blueprints
Create Date: 2026-06-20
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0022_system_cost_indices"
down_revision = "0021_esi_blueprints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())

    if "system_cost_indices" not in insp.get_table_names():
        op.create_table(
            "system_cost_indices",
            sa.Column("solar_system_id", sa.Integer(), primary_key=True),
            sa.Column("activity", sa.String(40), primary_key=True),
            sa.Column("cost_index", sa.Float(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    fac_cols = {c["name"] for c in insp.get_columns("facilities")}
    if "solar_system_id" not in fac_cols:
        op.add_column("facilities", sa.Column("solar_system_id", sa.Integer(), nullable=True))
        op.create_index("ix_facilities_solar_system_id", "facilities", ["solar_system_id"])


def downgrade() -> None:
    op.drop_index("ix_facilities_solar_system_id", table_name="facilities")
    op.drop_column("facilities", "solar_system_id")
    op.drop_table("system_cost_indices")
