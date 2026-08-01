"""add occurrence execution state and workflow touch accounting

Revision ID: 0060_add_occurrence_execution_state
Revises: 0059_add_paused_search_occurrences
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0060_add_occurrence_execution_state"
down_revision: str | None = "0059_add_paused_search_occurrences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lead_workflows",
        sa.Column("logical_touch_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "paused_search_occurrences",
        sa.Column("provider_delivery_status", sa.String(length=50)),
    )


def downgrade() -> None:
    op.drop_column("paused_search_occurrences", "provider_delivery_status")
    op.drop_column("lead_workflows", "logical_touch_count")