"""Character settings — role/grouping flags

Revision ID: 0016_character_flags
Revises: 0015_agenda_alerts
Create Date: 2026-06-19

Adds the Character Settings tab's criteria to ``character_settings``: a favourite
pin, whether the character counts toward overall capital / the common production
chain, manufacturer / trader role flags, and a free-text custom group.

Idempotent (add-column-if-missing) so re-runs / a half-applied chain converge.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0016_character_flags"
down_revision = "0015_agenda_alerts"
branch_labels = None
depends_on = None

_COLUMNS = [
    ("favorite", sa.Boolean(), {"nullable": False, "server_default": sa.false()}),
    ("track_wealth", sa.Boolean(), {"nullable": False, "server_default": sa.true()}),
    ("track_production", sa.Boolean(), {"nullable": False, "server_default": sa.true()}),
    ("is_manufacturer", sa.Boolean(), {"nullable": False, "server_default": sa.false()}),
    ("is_trader", sa.Boolean(), {"nullable": False, "server_default": sa.false()}),
    ("group_name", sa.String(60), {"nullable": True}),
]


def upgrade() -> None:
    have = {c["name"] for c in inspect(op.get_bind()).get_columns("character_settings")}
    for name, type_, kw in _COLUMNS:
        if name not in have:
            op.add_column("character_settings", sa.Column(name, type_, **kw))


def downgrade() -> None:
    for name, _type, _kw in reversed(_COLUMNS):
        op.drop_column("character_settings", name)
