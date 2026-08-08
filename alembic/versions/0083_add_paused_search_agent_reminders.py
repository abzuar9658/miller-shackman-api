"""add paused-search agent reminders

Revision ID: 0083_add_paused_search_agent_reminders
Revises: 0082_add_paused_search_policy_contract
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0083_add_paused_search_agent_reminders"
down_revision: str | None = "0082_add_paused_search_policy_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paused_search_agent_reminders",
        sa.Column("reminder_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("occurrence_id", sa.UUID(), nullable=False),
        sa.Column("assigned_user_id", sa.UUID(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["lead_workflows.workflow_id"]),
        sa.ForeignKeyConstraint(["occurrence_id"], ["paused_search_occurrences.occurrence_id"]),
        sa.PrimaryKeyConstraint("reminder_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_paused_search_agent_reminders_workspace_idempotency",
        ),
    )
    op.create_index(
        "ix_paused_search_agent_reminders_workspace_status_due",
        "paused_search_agent_reminders",
        ["workspace_id", "status", "due_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_paused_search_agent_reminders_workspace_status_due",
        table_name="paused_search_agent_reminders",
    )
    op.drop_table("paused_search_agent_reminders")