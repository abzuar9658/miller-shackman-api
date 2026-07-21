"""create rejected draft reviews

Revision ID: 0021
Revises: 0020_add_campaign_version_manual_enrollment_flag
Create Date: 2026-07-14 00:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0021"
down_revision = "0020_add_campaign_version_manual_enrollment_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rejected_draft_reviews",
        sa.Column("review_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("leads.lead_id"),
            nullable=False,
        ),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lead_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column(
            "workflow_transition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_transitions.transition_id"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaigns.campaign_id"),
            nullable=False,
        ),
        sa.Column(
            "campaign_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaign_versions.campaign_version_id"),
            nullable=False,
        ),
        sa.Column(
            "cadence_step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaign_cadence_steps.cadence_step_id"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("draft_reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review_blockers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("draft_safety_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "draft_personalization_notes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("draft_body", sa.String(), nullable=True),
        sa.Column("draft_subject", sa.String(length=255), nullable=True),
        sa.Column("raw_llm_response_text", sa.String(), nullable=True),
        sa.Column("validation_error", sa.String(), nullable=True),
        sa.Column("explanation", sa.String(), nullable=True),
        sa.Column("draft_confidence", sa.Float(), nullable=True),
        sa.Column("draft_model", sa.String(length=100), nullable=True),
        sa.Column("draft_prompt_version", sa.String(length=100), nullable=True),
        sa.Column("draft_latency_ms", sa.Integer(), nullable=True),
        sa.Column("draft_usage_tokens", sa.Integer(), nullable=True),
        sa.Column("message_version", sa.Integer(), nullable=False),
        sa.Column("can_approve_send", sa.Boolean(), nullable=False),
        sa.Column(
            "reviewed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(), nullable=True),
        sa.Column(
            "outbound_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outbound_messages.message_id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "workflow_transition_id",
            name="uq_rejected_draft_reviews_workspace_transition",
        ),
    )
    op.create_index(
        "ix_rejected_draft_reviews_workspace_lead_created",
        "rejected_draft_reviews",
        ["workspace_id", "lead_id", "created_at"],
    )
    op.create_index(
        "ix_rejected_draft_reviews_workspace_status_created",
        "rejected_draft_reviews",
        ["workspace_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_rejected_draft_reviews_workspace_status_created",
        table_name="rejected_draft_reviews",
    )
    op.drop_index(
        "ix_rejected_draft_reviews_workspace_lead_created",
        table_name="rejected_draft_reviews",
    )
    op.drop_table("rejected_draft_reviews")