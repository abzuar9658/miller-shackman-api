"""add paused-search notification policies, reviews, and notifications

Revision ID: 0063_add_paused_search_reviews_notifications
Revises: 0062_add_template_versions
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0063_add_paused_search_reviews_notifications"
down_revision: str | None = "0062_add_template_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paused_search_notification_policies",
        sa.Column("notification_policy_id", sa.UUID(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("enabled_events", sa.JSON(), nullable=False),
        sa.Column("recipient_roles", sa.JSON(), nullable=False),
        sa.Column("manager_escalation_hours", sa.Integer(), nullable=False),
        sa.Column("repeated_failure_threshold", sa.Integer(), nullable=False),
        sa.Column("digest_enabled", sa.Boolean(), nullable=False),
        sa.Column("digest_cadence_hours", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.UniqueConstraint(
            "workspace_id",
            "version",
            name="uq_paused_search_notification_policy_workspace_version",
        ),
    )
    op.create_index(
        "ix_paused_search_notification_policies_workspace_created",
        "paused_search_notification_policies",
        ["workspace_id", "created_at"],
    )

    op.create_table(
        "paused_search_reviews",
        sa.Column("review_id", sa.UUID(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("occurrence_id", sa.UUID()),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_expiry_at", sa.DateTime(timezone=True)),
        sa.Column("reviewer_user_id", sa.UUID()),
        sa.Column("acted_at", sa.DateTime(timezone=True)),
        sa.Column("action_reason", sa.String(1000)),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
    )
    op.create_index(
        "ix_paused_search_reviews_workspace_status_requested",
        "paused_search_reviews",
        ["workspace_id", "status", "requested_at"],
    )
    op.create_index(
        "ix_paused_search_reviews_workspace_workflow",
        "paused_search_reviews",
        ["workspace_id", "workflow_id"],
    )

    op.create_table(
        "paused_search_notifications",
        sa.Column("notification_id", sa.UUID(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("event", sa.String(100), nullable=False),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("idempotency_key", sa.String(500), nullable=False),
        sa.Column("recipient_user_id", sa.UUID()),
        sa.Column("recipient_destination", sa.String(320)),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("policy_id", sa.UUID(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.UUID()),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.String(1000)),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_paused_search_notifications_workspace_idempotency",
        ),
    )
    op.create_index(
        "ix_paused_search_notifications_workspace_status",
        "paused_search_notifications",
        ["workspace_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_paused_search_notifications_workspace_status",
        table_name="paused_search_notifications",
    )
    op.drop_table("paused_search_notifications")
    op.drop_index(
        "ix_paused_search_reviews_workspace_workflow",
        table_name="paused_search_reviews",
    )
    op.drop_index(
        "ix_paused_search_reviews_workspace_status_requested",
        table_name="paused_search_reviews",
    )
    op.drop_table("paused_search_reviews")
    op.drop_index(
        "ix_paused_search_notification_policies_workspace_created",
        table_name="paused_search_notification_policies",
    )
    op.drop_table("paused_search_notification_policies")
