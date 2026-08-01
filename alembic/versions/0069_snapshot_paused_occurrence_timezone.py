"""snapshot brokerage timezone on paused-search occurrences

Revision ID: 0069_snapshot_paused_occurrence_timezone
Revises: 0068_add_paused_occurrence_fallback_marker
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0069_snapshot_paused_occurrence_timezone"
down_revision: str | None = "0068_add_paused_occurrence_fallback_marker"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paused_search_occurrences",
        sa.Column("timezone_snapshot", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("paused_search_occurrences", "timezone_snapshot")