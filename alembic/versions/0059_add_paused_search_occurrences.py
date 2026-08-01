"""add paused-search occurrence foundation

Revision ID: 0059_add_paused_search_occurrences
Revises: 0058_add_recurring_paused_search_flag
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0059_add_paused_search_occurrences"
down_revision: str | None = "0058_add_recurring_paused_search_flag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "paused_search_occurrences"


def upgrade() -> None:
    op.add_column(
        "paused_search_track_versions",
        sa.Column("max_duration_days", sa.Integer(), nullable=False, server_default="365"),
    )
    op.add_column(
        "paused_search_track_versions",
        sa.Column(
            "terminal_behavior",
            sa.String(length=50),
            nullable=False,
            server_default="complete_keep_paused",
        ),
    )
    op.add_column("paused_search_track_steps", sa.Column("interval_days", sa.Integer()))
    op.add_column(
        "paused_search_track_steps",
        sa.Column("max_occurrences", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        _TABLE,
        sa.Column("occurrence_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column("lead_id", pg.UUID(as_uuid=True), sa.ForeignKey("leads.lead_id"), nullable=False),
        sa.Column(
            "workflow_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("lead_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column(
            "track_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("paused_search_track_versions.track_version_id"),
            nullable=False,
        ),
        sa.Column(
            "step_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("paused_search_track_steps.step_id"),
            nullable=False,
        ),
        sa.Column("phase", sa.String(length=50), nullable=False),
        sa.Column("occurrence_number", sa.Integer(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("idempotency_key", sa.String(length=500), nullable=False),
        sa.Column("logical_touch_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_message_id", sa.String(length=255)),
        sa.Column("correlation_id", pg.UUID(as_uuid=True)),
        sa.Column("failure_reason", sa.String(length=500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "workspace_id",
            "workflow_id",
            "track_version_id",
            "step_id",
            "occurrence_number",
            "scheduled_for",
            name="uq_paused_occurrences_workspace_identity",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_paused_occurrences_workspace_idempotency",
        ),
    )
    op.create_index(
        "ix_paused_occurrences_workspace_workflow_status",
        _TABLE,
        ["workspace_id", "workflow_id", "status"],
    )
    op.create_index(
        "ix_paused_occurrences_workspace_due",
        _TABLE,
        ["workspace_id", "status", "scheduled_for"],
    )
    _enable_workspace_rls(_TABLE)


def downgrade() -> None:
    _disable_workspace_rls(_TABLE)
    op.drop_index("ix_paused_occurrences_workspace_due", table_name=_TABLE)
    op.drop_index("ix_paused_occurrences_workspace_workflow_status", table_name=_TABLE)
    op.drop_table(_TABLE)
    op.drop_column("paused_search_track_steps", "max_occurrences")
    op.drop_column("paused_search_track_steps", "interval_days")
    op.drop_column("paused_search_track_versions", "terminal_behavior")
    op.drop_column("paused_search_track_versions", "max_duration_days")


def _enable_workspace_rls(table_name: str) -> None:
    policy_name = f"rls_{table_name}_workspace_isolation"
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"')
    op.execute(
        f'''CREATE POLICY "{policy_name}" ON "{table_name}"
        USING (app_rls_service_access_enabled() OR workspace_id = app_current_workspace_id())
        WITH CHECK (
            app_rls_service_access_enabled() OR workspace_id = app_current_workspace_id()
        )'''
    )


def _disable_workspace_rls(table_name: str) -> None:
    policy_name = f"rls_{table_name}_workspace_isolation"
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"')
    op.execute(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')