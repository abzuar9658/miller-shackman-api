"""create durable outbound provider dispatch requests

Revision ID: 0089_create_outbound_send_requests
Revises: 0088_extend_external_event_retry
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0089_create_outbound_send_requests"
down_revision: str | None = "0088_extend_external_event_retry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbound_send_requests",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("temporal_workflow_id", sa.String(length=255), nullable=False),
        sa.Column("outbound_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reconciliation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=500), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("provider_name", sa.String(length=50), nullable=False),
        sa.Column("provider_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("failure_kind", sa.String(length=50), nullable=True),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.ForeignKeyConstraint(["outbound_message_id"], ["outbound_messages.message_id"]),
        sa.ForeignKeyConstraint(
            ["reconciliation_id"],
            ["outbound_send_reconciliations.reconciliation_id"],
        ),
        sa.PrimaryKeyConstraint("request_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_outbound_send_requests_workspace_idempotency",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "outbound_message_id",
            name="uq_outbound_send_requests_workspace_message",
        ),
    )
    op.create_index(
        "ix_outbound_send_requests_status_available_created",
        "outbound_send_requests",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_outbound_send_requests_workspace_status_created",
        "outbound_send_requests",
        ["workspace_id", "status", "created_at"],
    )
    _enable_workspace_rls()


def downgrade() -> None:
    _disable_workspace_rls()
    op.drop_index(
        "ix_outbound_send_requests_workspace_status_created",
        table_name="outbound_send_requests",
    )
    op.drop_index(
        "ix_outbound_send_requests_status_available_created",
        table_name="outbound_send_requests",
    )
    op.drop_table("outbound_send_requests")


def _enable_workspace_rls() -> None:
    policy_name = "rls_outbound_send_requests_workspace_isolation"
    op.execute('ALTER TABLE "outbound_send_requests" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "outbound_send_requests" FORCE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "outbound_send_requests"')
    op.execute(
        f'''CREATE POLICY "{policy_name}" ON "outbound_send_requests"
        USING (app_rls_service_access_enabled() OR workspace_id = app_current_workspace_id())
        WITH CHECK (
            app_rls_service_access_enabled() OR workspace_id = app_current_workspace_id()
        )'''
    )


def _disable_workspace_rls() -> None:
    policy_name = "rls_outbound_send_requests_workspace_isolation"
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "outbound_send_requests"')
    op.execute('ALTER TABLE "outbound_send_requests" NO FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "outbound_send_requests" DISABLE ROW LEVEL SECURITY')