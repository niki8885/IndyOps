"""baseline — full current app schema

Faithful baseline built from the live models (so it matches what create_all
produced historically, enums and all). Existing databases are adopted by
``alembic stamp 0001_baseline``; fresh databases get the whole schema here.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-15
"""
from alembic import op

from app.core.database import Base

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
