"""add durable outbound provider failure state

Revision ID: 0087_add_provider_failure_state
Revises: 0086_create_outbound_send_reconciliations
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0087_add_provider_failure_state"
down_revision: str | None = "0086_create_outbound_send_reconciliations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbound_messages",
        sa.Column("provider_attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "outbound_messages",
        sa.Column("provider_last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbound_messages",
        sa.Column("provider_next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbound_messages",
        sa.Column("provider_last_failure_kind", sa.String(length=50), nullable=True),
    )
    op.alter_column("outbound_messages", "provider_attempt_count", server_default=None)

    op.create_table(
        "outbound_provider_failures",
        sa.Column("failure_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outbound_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("provider_name", sa.String(length=50), nullable=False),
        sa.Column("failure_kind", sa.String(length=50), nullable=False),
        sa.Column("failure_reason", sa.String(length=500), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["outbound_message_id"], ["outbound_messages.message_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("failure_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "outbound_message_id",
            name="uq_outbound_provider_failures_workspace_message",
        ),
    )
    op.create_index(
        "ix_outbound_provider_failures_workspace_status_created",
        "outbound_provider_failures",
        ["workspace_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbound_provider_failures_workspace_status_created",
        table_name="outbound_provider_failures",
    )
    op.drop_table("outbound_provider_failures")
    op.drop_column("outbound_messages", "provider_last_failure_kind")
    op.drop_column("outbound_messages", "provider_next_retry_at")
    op.drop_column("outbound_messages", "provider_last_attempt_at")
    op.drop_column("outbound_messages", "provider_attempt_count")