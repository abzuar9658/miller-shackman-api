"""persist paused-search fallback usage

Revision ID: 0068_add_paused_occurrence_fallback_marker
Revises: 0067_enforce_active_paused_search_workflow_overlap
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0068_add_paused_occurrence_fallback_marker"
down_revision: str | None = "0067_enforce_active_paused_search_workflow_overlap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paused_search_occurrences",
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("paused_search_occurrences", "fallback_used", server_default=None)


def downgrade() -> None:
    op.drop_column("paused_search_occurrences", "fallback_used")