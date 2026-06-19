"""Add scenario_analyses table (IO-23 Scenario Simulation engine)

Revision ID: 0018_scenario_analyses
Revises: 0017_job_kind
Create Date: 2026-06-19
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0018_scenario_analyses"
down_revision = "0017_job_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: create_all may already have built the table on a fresh DB.
    if "scenario_analyses" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "scenario_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("source", sa.String(12), nullable=False, server_default="chain"),
        sa.Column("target_type_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("product_name", sa.String(200), nullable=True),
        sa.Column("engine", sa.String(12), nullable=False, server_default="python"),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("baseline", sa.JSON(), nullable=False),
        sa.Column("outcomes", sa.JSON(), nullable=False),
        sa.Column("ranking", sa.JSON(), nullable=True),
        sa.Column("pdf", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_scenario_analyses_user_id", "scenario_analyses", ["user_id"])
    op.create_index("ix_scenario_analyses_project_id", "scenario_analyses", ["project_id"])
    op.create_index("ix_scenario_analyses_target_type_id", "scenario_analyses", ["target_type_id"])
    op.create_index("ix_scenario_analyses_created_at", "scenario_analyses", ["created_at"])


def downgrade() -> None:
    op.drop_table("scenario_analyses")
