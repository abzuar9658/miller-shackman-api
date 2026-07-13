"""add outbound delivery tracking fields

Revision ID: 0014_add_outbound_delivery_tracking_fields
Revises: 0013_align_preflight_digest_schema
Create Date: 2026-07-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_add_outbound_delivery_tracking_fields"
down_revision: str | None = "0013_align_preflight_digest_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbound_messages", sa.Column("provider_name", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "outbound_messages",
        sa.Column("provider_delivery_status", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "outbound_messages",
        sa.Column("provider_status_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbound_messages", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_index(
        "ix_outbound_messages_provider_message",
        "outbound_messages",
        ["provider_name", "provider_message_id"],
    )
    op.create_index(
        "ix_provider_message_events_provider_external",
        "provider_message_events",
        ["provider", "external_provider_event_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_message_events_provider_external",
        table_name="provider_message_events",
    )
    op.drop_index("ix_outbound_messages_provider_message", table_name="outbound_messages")
    op.drop_column("outbound_messages", "delivered_at")
    op.drop_column("outbound_messages", "provider_status_updated_at")
    op.drop_column("outbound_messages", "provider_delivery_status")
    op.drop_column("outbound_messages", "provider_name")
