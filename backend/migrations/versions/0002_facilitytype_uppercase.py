"""Add uppercase ATHANOR/TATARA to facilitytype enum

SQLAlchemy stores Python enum .name (uppercase), but the enum type was
originally extended with title-case values ('Athanor', 'Tatara'). This
adds the uppercase variants that the ORM actually inserts.

Revision ID: 0002_facilitytype_uppercase
Revises: 0001_baseline
Create Date: 2026-06-15
"""
from alembic import op

revision = "0002_facilitytype_uppercase"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execution_options(isolation_level="AUTOCOMMIT")
    for val in ("Athanor", "Tatara", "ATHANOR", "TATARA"):
        conn.execute(
            __import__("sqlalchemy").text(
                f"ALTER TYPE facilitytype ADD VALUE IF NOT EXISTS '{val}'"
            )
        )


def downgrade() -> None:
    pass  # PostgreSQL does not support removing enum values
