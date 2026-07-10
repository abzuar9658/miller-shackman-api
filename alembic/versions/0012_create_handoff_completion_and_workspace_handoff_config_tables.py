"""create handoff completion and workspace handoff config tables

Revision ID: 0012_handoff_completion_and_workspace_handoff_config
Revises: 0011_workspace_contact_policy_table
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_handoff_completion_and_workspace_handoff_config"
down_revision: str | None = "0011_workspace_contact_policy_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_handoff_configs",
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column("fallback_recipient_email", sa.String(length=320), nullable=True),
        sa.Column("crm_handoff_tag", sa.String(length=255), nullable=True),
        sa.Column(
            "crm_custom_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_table(
        "handoff_completions",
        sa.Column(
            "handoff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("handoffs.handoff_id"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column("notification_idempotency_key", sa.String(length=500), nullable=False),
        sa.Column("notification_recipient_id", sa.String(length=255), nullable=True),
        sa.Column("notification_recipient_destination", sa.String(length=320), nullable=True),
        sa.Column("notification_provider_reference", sa.String(length=255), nullable=True),
        sa.Column("notification_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("crm_note_written_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("crm_tag_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("crm_custom_fields_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("handoff_id"),
    )
    op.create_index(
        "ix_handoff_completions_workspace_completed",
        "handoff_completions",
        ["workspace_id", "completed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_handoff_completions_workspace_completed", table_name="handoff_completions")
    op.drop_table("handoff_completions")
    op.drop_table("workspace_handoff_configs")