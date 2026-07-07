"""create conversation handoff tables

Revision ID: 0009_conversation_handoff_tables
Revises: 0008_preflight_tables
Create Date: 2026-07-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_conversation_handoff_tables"
down_revision: str | None = "0008_preflight_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("ai_interaction_count", sa.Integer(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.campaign_id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["lead_workflows.workflow_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("conversation_id"),
    )
    op.create_index(
        "ix_conversations_workspace_lead_updated",
        "conversations",
        ["workspace_id", "lead_id", "updated_at"],
    )
    op.create_index(
        "ix_conversations_workspace_status", "conversations", ["workspace_id", "status"]
    )

    op.create_table(
        "inbound_messages",
        sa.Column("inbound_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=False),
        sa.Column("external_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("from_address_redacted", sa.String(length=255), nullable=True),
        sa.Column("to_address_redacted", sa.String(length=255), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("classification_status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.conversation_id"]),
        sa.ForeignKeyConstraint(["external_event_id"], ["external_events.external_event_id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("inbound_message_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "provider_message_id",
            name="uq_inbound_messages_workspace_provider_message",
        ),
    )
    op.create_index(
        "ix_inbound_messages_workspace_lead_received",
        "inbound_messages",
        ["workspace_id", "lead_id", "received_at"],
    )
    op.create_index(
        "ix_inbound_messages_workspace_classification",
        "inbound_messages",
        ["workspace_id", "classification_status"],
    )

    op.create_table(
        "conversation_summaries",
        sa.Column("summary_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("preferences", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.conversation_id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("summary_id"),
    )
    op.create_index(
        "ix_conversation_summaries_workspace_conversation_created",
        "conversation_summaries",
        ["workspace_id", "conversation_id", "created_at"],
    )

    op.create_table(
        "handoffs",
        sa.Column("handoff_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("inbound_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_agent_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_agent_crm_id", sa.String(length=255), nullable=True),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("latest_inbound_text", sa.Text(), nullable=True),
        sa.Column("preferences", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assigned_agent_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.campaign_id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.conversation_id"]),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["inbound_messages.inbound_message_id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["lead_workflows.workflow_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("handoff_id"),
    )
    op.create_index(
        "ix_handoffs_workspace_status_created", "handoffs", ["workspace_id", "status", "created_at"]
    )
    op.create_index(
        "ix_handoffs_workspace_agent_status",
        "handoffs",
        ["workspace_id", "assigned_agent_user_id", "status"],
    )

    op.add_column(
        "outbound_messages", sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "outbound_messages",
        sa.Column("campaign_enrollment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "outbound_messages",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "outbound_messages",
        sa.Column("reply_to_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_outbound_messages_workflow",
        "outbound_messages",
        "lead_workflows",
        ["workflow_id"],
        ["workflow_id"],
    )
    op.create_foreign_key(
        "fk_outbound_messages_enrollment",
        "outbound_messages",
        "campaign_enrollments",
        ["campaign_enrollment_id"],
        ["campaign_enrollment_id"],
    )
    op.create_foreign_key(
        "fk_outbound_messages_conversation",
        "outbound_messages",
        "conversations",
        ["conversation_id"],
        ["conversation_id"],
    )
    op.create_foreign_key(
        "fk_outbound_messages_reply_to",
        "outbound_messages",
        "outbound_messages",
        ["reply_to_message_id"],
        ["message_id"],
    )
    op.create_index(
        "ix_outbound_messages_workspace_workflow",
        "outbound_messages",
        ["workspace_id", "workflow_id"],
    )
    op.create_index(
        "ix_outbound_messages_workspace_conversation",
        "outbound_messages",
        ["workspace_id", "conversation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbound_messages_workspace_conversation", table_name="outbound_messages")
    op.drop_index("ix_outbound_messages_workspace_workflow", table_name="outbound_messages")
    op.drop_constraint("fk_outbound_messages_reply_to", "outbound_messages", type_="foreignkey")
    op.drop_constraint("fk_outbound_messages_conversation", "outbound_messages", type_="foreignkey")
    op.drop_constraint("fk_outbound_messages_enrollment", "outbound_messages", type_="foreignkey")
    op.drop_constraint("fk_outbound_messages_workflow", "outbound_messages", type_="foreignkey")
    op.drop_column("outbound_messages", "reply_to_message_id")
    op.drop_column("outbound_messages", "conversation_id")
    op.drop_column("outbound_messages", "campaign_enrollment_id")
    op.drop_column("outbound_messages", "workflow_id")

    op.drop_index("ix_handoffs_workspace_agent_status", table_name="handoffs")
    op.drop_index("ix_handoffs_workspace_status_created", table_name="handoffs")
    op.drop_table("handoffs")
    op.drop_index(
        "ix_conversation_summaries_workspace_conversation_created",
        table_name="conversation_summaries",
    )
    op.drop_table("conversation_summaries")
    op.drop_index("ix_inbound_messages_workspace_classification", table_name="inbound_messages")
    op.drop_index("ix_inbound_messages_workspace_lead_received", table_name="inbound_messages")
    op.drop_table("inbound_messages")
    op.drop_index("ix_conversations_workspace_status", table_name="conversations")
    op.drop_index("ix_conversations_workspace_lead_updated", table_name="conversations")
    op.drop_table("conversations")
