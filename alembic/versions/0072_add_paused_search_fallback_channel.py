"""add one permitted paused-search fallback channel

Revision ID: 0072_add_paused_search_fallback_channel
Revises: 0071_add_paused_search_timing_basis
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0072_add_paused_search_fallback_channel"
down_revision: str | None = "0071_add_paused_search_timing_basis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paused_search_track_steps",
        sa.Column("fallback_channel", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("paused_search_track_steps", "fallback_channel")