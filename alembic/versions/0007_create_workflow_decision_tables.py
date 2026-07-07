"""create workflow decision tables

Revision ID: 0007_workflow_decision_tables
Revises: 0006_campaign_tables
Create Date: 2026-07-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_workflow_decision_tables"
down_revision: str | None = "0006_campaign_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campaign_enrollments",
        sa.Column("campaign_enrollment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("eligible_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.campaign_id"]),
        sa.ForeignKeyConstraint(["campaign_version_id"], ["campaign_versions.campaign_version_id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("campaign_enrollment_id"),
    )
    op.create_index(
        "ix_campaign_enrollments_workspace_status_created",
        "campaign_enrollments",
        ["workspace_id", "status", "created_at"],
    )
    op.create_index(
        "ix_campaign_enrollments_workspace_lead_created",
        "campaign_enrollments",
        ["workspace_id", "lead_id", "created_at"],
    )
    op.create_index(
        "uq_campaign_enrollments_active_lead_campaign",
        "campaign_enrollments",
        ["workspace_id", "campaign_id", "lead_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('candidate', 'queued', 'active', 'paused', 'handoff')",
        ),
    )

    op.create_table(
        "lead_workflows",
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("temporal_workflow_id", sa.String(length=255), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_enrollment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=50), nullable=False),
        sa.Column("current_step_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_transition_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pause_reason", sa.String(length=255), nullable=True),
        sa.Column("resume_reason", sa.String(length=500), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_enrollment_id"], ["campaign_enrollments.campaign_enrollment_id"]
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.campaign_id"]),
        sa.ForeignKeyConstraint(["current_step_id"], ["campaign_cadence_steps.cadence_step_id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("workflow_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "temporal_workflow_id",
            name="uq_lead_workflows_workspace_temporal_id",
        ),
    )
    op.create_index(
        "ix_lead_workflows_workspace_state_next",
        "lead_workflows",
        ["workspace_id", "state", "next_action_at"],
    )
    op.create_index(
        "ix_lead_workflows_workspace_lead_transition",
        "lead_workflows",
        ["workspace_id", "lead_id", "last_transition_at"],
    )

    op.create_table(
        "workflow_transitions",
        sa.Column("transition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_state", sa.String(length=50), nullable=True),
        sa.Column("to_state", sa.String(length=50), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.campaign_id"]),
        sa.ForeignKeyConstraint(["external_event_id"], ["external_events.external_event_id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["lead_workflows.workflow_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("transition_id"),
    )
    op.create_index(
        "ix_workflow_transitions_workspace_workflow_created",
        "workflow_transitions",
        ["workspace_id", "workflow_id", "created_at"],
    )

    op.create_table(
        "decision_audit_events",
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision_type", sa.String(length=100), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=True),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column("facts_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ai_provider", sa.String(length=50), nullable=True),
        sa.Column("ai_model", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=100), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.campaign_id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["lead_workflows.workflow_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("decision_id"),
    )
    op.create_index(
        "ix_decision_audit_events_workspace_lead_created",
        "decision_audit_events",
        ["workspace_id", "lead_id", "created_at"],
    )
    op.create_index(
        "ix_decision_audit_events_workspace_type_created",
        "decision_audit_events",
        ["workspace_id", "decision_type", "created_at"],
    )
    op.create_index(
        "ix_decision_audit_events_workspace_campaign_allowed",
        "decision_audit_events",
        ["workspace_id", "campaign_id", "allowed", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_decision_audit_events_workspace_campaign_allowed", table_name="decision_audit_events"
    )
    op.drop_index(
        "ix_decision_audit_events_workspace_type_created", table_name="decision_audit_events"
    )
    op.drop_index(
        "ix_decision_audit_events_workspace_lead_created", table_name="decision_audit_events"
    )
    op.drop_table("decision_audit_events")
    op.drop_index(
        "ix_workflow_transitions_workspace_workflow_created", table_name="workflow_transitions"
    )
    op.drop_table("workflow_transitions")
    op.drop_index("ix_lead_workflows_workspace_lead_transition", table_name="lead_workflows")
    op.drop_index("ix_lead_workflows_workspace_state_next", table_name="lead_workflows")
    op.drop_table("lead_workflows")
    op.drop_index("uq_campaign_enrollments_active_lead_campaign", table_name="campaign_enrollments")
    op.drop_index(
        "ix_campaign_enrollments_workspace_lead_created", table_name="campaign_enrollments"
    )
    op.drop_index(
        "ix_campaign_enrollments_workspace_status_created", table_name="campaign_enrollments"
    )
    op.drop_table("campaign_enrollments")
