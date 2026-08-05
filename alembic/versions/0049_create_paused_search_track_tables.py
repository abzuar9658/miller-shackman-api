"""create paused-search track tables

Revision ID: 0049_create_paused_search_track_tables
Revises: 0048_add_lead_classification_artifacts_and_ai_actor
Create Date: 2026-07-25 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0049_create_paused_search_track_tables"
down_revision = "0048_add_lead_classification_artifacts_and_ai_actor"
branch_labels = None
depends_on = None

_TABLES = (
    "paused_search_tracks",
    "paused_search_track_versions",
    "paused_search_track_steps",
    "paused_search_track_admin_audit_logs",
)


def upgrade() -> None:
    op.create_table(
        "paused_search_tracks",
        sa.Column("track_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column("track_key", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("active_version_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_by_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "track_key", name="uq_paused_tracks_workspace_key"),
    )
    op.create_index(
        "ix_paused_tracks_workspace_status", "paused_search_tracks", ["workspace_id", "status"]
    )

    op.create_table(
        "paused_search_track_versions",
        sa.Column("track_version_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column(
            "track_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("paused_search_tracks.track_id"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("selection_guidance", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "allowed_channels", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("fallback_timing_policy", sa.String(100), nullable=False),
        sa.Column("maintenance_interval_days", sa.Integer(), nullable=False),
        sa.Column("reactivation_window_days", sa.Integer(), nullable=False),
        sa.Column("max_total_touches", sa.Integer(), nullable=False),
        sa.Column(
            "created_by_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "track_id",
            "version_number",
            name="uq_paused_track_versions_workspace_track_version",
        ),
    )
    op.create_index(
        "ix_paused_track_versions_workspace_track_status",
        "paused_search_track_versions",
        ["workspace_id", "track_id", "status"],
    )

    op.create_table(
        "paused_search_track_steps",
        sa.Column("step_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column(
            "track_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("paused_search_track_versions.track_version_id"),
            nullable=False,
        ),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(50), nullable=False),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("delay_hours", sa.Integer(), nullable=False),
        sa.Column("message_goal", sa.String(500), nullable=False),
        sa.Column("template_key", sa.String(255), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "track_version_id",
            "step_order",
            name="uq_paused_track_steps_workspace_version_order",
        ),
    )

    op.create_table(
        "paused_search_track_admin_audit_logs",
        sa.Column("audit_log_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column(
            "track_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("paused_search_tracks.track_id"),
            nullable=False,
        ),
        sa.Column(
            "track_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("paused_search_track_versions.track_version_id"),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.user_id"), nullable=False
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("details", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_paused_track_audit_workspace_track",
        "paused_search_track_admin_audit_logs",
        ["workspace_id", "track_id", "created_at"],
    )
    op.create_index(
        "ix_paused_track_audit_workspace_action",
        "paused_search_track_admin_audit_logs",
        ["workspace_id", "action", "created_at"],
    )

    for table_name in _TABLES:
        _enable_workspace_rls(table_name)
    op.create_foreign_key(
        "fk_lead_classification_artifact_track_version",
        "lead_classification_artifacts",
        "paused_search_track_versions",
        ["track_version_id"],
        ["track_version_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_lead_classification_artifact_track_version",
        "lead_classification_artifacts",
        type_="foreignkey",
    )
    for table_name in reversed(_TABLES):
        _disable_workspace_rls(table_name)
    op.drop_table("paused_search_track_admin_audit_logs")
    op.drop_table("paused_search_track_steps")
    op.drop_table("paused_search_track_versions")
    op.drop_table("paused_search_tracks")


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
