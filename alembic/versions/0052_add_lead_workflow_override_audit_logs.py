"""add lead workflow override audit logs

Revision ID: 0052_add_lead_workflow_override_audit_logs
Revises: 0051_add_paused_search_track_step_to_workflows
Create Date: 2026-07-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0052_add_lead_workflow_override_audit_logs"
down_revision: str | None = "0051_add_paused_search_track_step_to_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lead_workflow_override_audit_logs",
        sa.Column(
            "audit_log_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["lead_workflows.workflow_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("audit_log_id"),
    )
    op.create_index(
        "ix_lead_workflow_override_audit_workspace_lead",
        "lead_workflow_override_audit_logs",
        ["workspace_id", "lead_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_lead_workflow_override_audit_workspace_action",
        "lead_workflow_override_audit_logs",
        ["workspace_id", "action", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lead_workflow_override_audit_workspace_action",
        table_name="lead_workflow_override_audit_logs",
    )
    op.drop_index(
        "ix_lead_workflow_override_audit_workspace_lead",
        table_name="lead_workflow_override_audit_logs",
    )
    op.drop_table("lead_workflow_override_audit_logs")