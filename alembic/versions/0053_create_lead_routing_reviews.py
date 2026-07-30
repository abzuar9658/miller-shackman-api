"""create lead routing reviews

Revision ID: 0053_create_lead_routing_reviews
Revises: 0052_add_lead_workflow_override_audit_logs
Create Date: 2026-07-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0053_create_lead_routing_reviews"
down_revision: str | None = "0052_add_lead_workflow_override_audit_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RLS_TABLE = "lead_routing_reviews"


def upgrade() -> None:
    op.create_table(
        _RLS_TABLE,
        sa.Column("review_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("leads.lead_id"),
            nullable=False,
        ),
        sa.Column(
            "artifact_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("lead_classification_artifacts.artifact_id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("reason_codes", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("resolution", sa.String(length=100), nullable=True),
        sa.Column("reviewed_by_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.user_id")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "artifact_id",
            name="uq_lead_routing_reviews_workspace_artifact",
        ),
    )
    op.create_index(
        "ix_lead_routing_reviews_workspace_status_created",
        _RLS_TABLE,
        ["workspace_id", "status", "created_at"],
    )
    op.create_index(
        "ix_lead_routing_reviews_workspace_lead_created",
        _RLS_TABLE,
        ["workspace_id", "lead_id", "created_at"],
    )

    _enable_workspace_rls(_RLS_TABLE)


def downgrade() -> None:
    _disable_workspace_rls(_RLS_TABLE)
    op.drop_index(
        "ix_lead_routing_reviews_workspace_lead_created",
        table_name=_RLS_TABLE,
    )
    op.drop_index(
        "ix_lead_routing_reviews_workspace_status_created",
        table_name=_RLS_TABLE,
    )
    op.drop_table(_RLS_TABLE)


def _enable_workspace_rls(table_name: str) -> None:
    policy_name = _policy_name(table_name)
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"')
    op.execute(
        f'''
        CREATE POLICY "{policy_name}" ON "{table_name}"
        USING (
            app_rls_service_access_enabled() OR workspace_id = app_current_workspace_id()
        )
        WITH CHECK (
            app_rls_service_access_enabled() OR workspace_id = app_current_workspace_id()
        )
        '''
    )


def _disable_workspace_rls(table_name: str) -> None:
    policy_name = _policy_name(table_name)
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"')
    op.execute(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')


def _policy_name(table_name: str) -> str:
    return f"rls_{table_name}_workspace_isolation"