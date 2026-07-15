"""create crm conversation events table

Revision ID: 0019_create_crm_conversation_events
Revises: 0018
Create Date: 2026-07-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019_create_crm_conversation_events"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crm_conversation_events",
        sa.Column("crm_conversation_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("crm_provider", sa.String(length=50), nullable=False),
        sa.Column("crm_activity_id", sa.String(length=255), nullable=False),
        sa.Column("activity_type", sa.String(length=100), nullable=False),
        sa.Column("direction", sa.String(length=50), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content", sa.String(), nullable=True),
        sa.Column("actor_agent_id", sa.String(length=255), nullable=True),
        sa.Column("actor_name", sa.String(length=255), nullable=True),
        sa.Column("source_payload_version", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.conversation_id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("crm_conversation_event_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "crm_provider",
            "crm_activity_id",
            name="uq_crm_conversation_events_workspace_provider_activity",
        ),
    )
    op.create_index(
        "ix_crm_conversation_events_workspace_lead_occurred",
        "crm_conversation_events",
        ["workspace_id", "lead_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crm_conversation_events_workspace_lead_occurred",
        table_name="crm_conversation_events",
    )
    op.drop_table("crm_conversation_events")
