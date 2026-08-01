"""add default pause duration to paused-search track versions

Revision ID: 0070_add_default_pause_duration_days
Revises: 0069_snapshot_paused_occurrence_timezone
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0070_add_default_pause_duration_days"
down_revision: str | None = "0069_snapshot_paused_occurrence_timezone"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paused_search_track_versions",
        sa.Column(
            "default_pause_duration_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("60"),
        ),
    )
    op.alter_column(
        "paused_search_track_versions",
        "default_pause_duration_days",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("paused_search_track_versions", "default_pause_duration_days")