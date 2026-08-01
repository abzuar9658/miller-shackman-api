"""add explicit timing basis to paused-search steps

Revision ID: 0071_add_paused_search_timing_basis
Revises: 0070_add_default_pause_duration_days
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0071_add_paused_search_timing_basis"
down_revision: str | None = "0070_add_default_pause_duration_days"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paused_search_track_steps",
        sa.Column(
            "timing_basis",
            sa.String(length=50),
            nullable=False,
            server_default="customer_reengagement_date",
        ),
    )
    op.alter_column(
        "paused_search_track_steps",
        "timing_basis",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("paused_search_track_steps", "timing_basis")