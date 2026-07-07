"""create outbound messages table

Revision ID: 0002_create_outbound_messages
Revises: 0001_create_leads
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_create_outbound_messages"
down_revision: str | None = "0001_create_leads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbound_messages",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cadence_step_id", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("idempotency_key", sa.String(length=500), nullable=False),
        sa.Column("body", sa.String(length=4000), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("html_body", sa.String(length=8000), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_version", sa.Integer(), nullable=False),
        sa.Column("provider_send_status", sa.String(length=50), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column("draft_prompt_version", sa.String(length=100), nullable=True),
        sa.Column("draft_model", sa.String(length=100), nullable=True),
        sa.Column("draft_latency_ms", sa.Integer(), nullable=True),
        sa.Column("draft_usage_tokens", sa.Integer(), nullable=True),
        sa.Column("draft_confidence", sa.Float(), nullable=True),
        sa.Column(
            "draft_personalization_notes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("draft_safety_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("message_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_outbound_messages_workspace_idempotency_key",
        ),
    )
    op.create_index(
        "ix_outbound_messages_workspace_lead",
        "outbound_messages",
        ["workspace_id", "lead_id"],
    )
    op.create_index(
        "ix_outbound_messages_workspace_status",
        "outbound_messages",
        ["workspace_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbound_messages_workspace_status", table_name="outbound_messages")
    op.drop_index("ix_outbound_messages_workspace_lead", table_name="outbound_messages")
    op.drop_table("outbound_messages")
