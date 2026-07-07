"""create provider outbox tables

Revision ID: 0010_provider_outbox_tables
Revises: 0009_conversation_handoff_tables
Create Date: 2026-07-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_provider_outbox_tables"
down_revision: str | None = "0009_conversation_handoff_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_message_events",
        sa.Column("provider_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=False),
        sa.Column("outbound_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_redacted", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["outbound_message_id"], ["outbound_messages.message_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("provider_event_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "external_provider_event_id",
            name="uq_provider_message_events_workspace_provider_event",
        ),
    )
    op.create_index(
        "ix_provider_message_events_workspace_message",
        "provider_message_events",
        ["workspace_id", "provider_message_id"],
    )
    op.create_index(
        "ix_provider_message_events_workspace_status_received",
        "provider_message_events",
        ["workspace_id", "status", "received_at"],
    )

    op.create_table(
        "outbox_events",
        sa.Column("outbox_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("outbox_event_id"),
    )
    op.create_index(
        "ix_outbox_events_status_available", "outbox_events", ["status", "available_at"]
    )
    op.create_index(
        "ix_outbox_events_workspace_type_created",
        "outbox_events",
        ["workspace_id", "event_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_workspace_type_created", table_name="outbox_events")
    op.drop_index("ix_outbox_events_status_available", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index(
        "ix_provider_message_events_workspace_status_received", table_name="provider_message_events"
    )
    op.drop_index(
        "ix_provider_message_events_workspace_message", table_name="provider_message_events"
    )
    op.drop_table("provider_message_events")
