"""Add simulation_runs table (IO-22 Monte-Carlo profit simulator)

Revision ID: 0005_simulation_runs
Revises: 0004_blueprints
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_simulation_runs"
down_revision = "0004_blueprints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "simulation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("source", sa.String(12), nullable=False, server_default="chain"),
        sa.Column("target_type_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("n_iterations", sa.Integer(), nullable=False, server_default="25000"),
        sa.Column("engine", sa.String(12), nullable=False, server_default="python"),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("pdf", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_simulation_runs_user_id", "simulation_runs", ["user_id"])
    op.create_index("ix_simulation_runs_project_id", "simulation_runs", ["project_id"])
    op.create_index("ix_simulation_runs_created_at", "simulation_runs", ["created_at"])


def downgrade() -> None:
    op.drop_table("simulation_runs")
