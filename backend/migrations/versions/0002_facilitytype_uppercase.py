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
    # Postgres 12+ allows ``ALTER TYPE … ADD VALUE`` inside a transaction (as long as
    # the new value isn't used in the same tx — it isn't here). The previous version
    # forced AUTOCOMMIT on the bind, which newer SQLAlchemy rejects mid-transaction
    # ("isolation_level may not be altered…") and aborted the whole upgrade.
    for val in ("Athanor", "Tatara", "ATHANOR", "TATARA"):
        op.execute(f"ALTER TYPE facilitytype ADD VALUE IF NOT EXISTS '{val}'")


def downgrade() -> None:
    pass  # PostgreSQL does not support removing enum values
