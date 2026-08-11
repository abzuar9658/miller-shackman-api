"""add durable CRM external event retry state

Revision ID: 0088_extend_external_event_retry
Revises: 0087_add_provider_failure_state
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0088_extend_external_event_retry"
down_revision: str | None = "0087_add_provider_failure_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "external_events",
        sa.Column("failure_kind", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "external_events",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "external_events",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("external_events", "attempt_count", server_default=None)
    op.create_index(
        "ix_external_events_retryable_due",
        "external_events",
        ["status", "next_retry_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_external_events_retryable_due", table_name="external_events")
    op.drop_column("external_events", "next_retry_at")
    op.drop_column("external_events", "attempt_count")
    op.drop_column("external_events", "failure_kind")