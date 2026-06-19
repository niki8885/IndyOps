"""Add quiz_results table (Encyclopedia article quizzes, scored per section)

Revision ID: 0020_quiz_results
Revises: 0019_share_codes
Create Date: 2026-06-19
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0020_quiz_results"
down_revision = "0019_share_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "quiz_results" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "quiz_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("section", sa.String(40), nullable=False),
        sa.Column("article_key", sa.String(60), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_quiz_results_user_id", "quiz_results", ["user_id"])
    op.create_index("ix_quiz_results_section", "quiz_results", ["section"])
    op.create_index("ix_quiz_results_article_key", "quiz_results", ["article_key"])
    op.create_index("ix_quiz_results_created_at", "quiz_results", ["created_at"])


def downgrade() -> None:
    op.drop_table("quiz_results")
