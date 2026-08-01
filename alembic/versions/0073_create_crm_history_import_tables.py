"""create staged CRM history import tables

Revision ID: 0073_create_crm_history_import_tables
Revises: 0072_add_paused_search_fallback_channel
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0073_create_crm_history_import_tables"
down_revision: str | None = "0072_add_paused_search_fallback_channel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("crm_history_import_jobs", "crm_history_import_events")


def upgrade() -> None:
    op.create_table(
        "crm_history_import_jobs",
        sa.Column("import_job_id", postgresql.UUID(as_uuid=True), primary_key=True),
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
        sa.Column("crm_lead_id", sa.String(255), nullable=False),
        sa.Column(
            "requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("upload_token_hash", sa.String(64), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("promoted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("upload_completed_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "import_job_id",
            name="uq_crm_history_import_jobs_workspace_job",
        ),
    )
    op.create_index(
        "uq_crm_history_import_jobs_one_active_lead",
        "crm_history_import_jobs",
        ["workspace_id", "lead_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending', 'receiving', 'ready', 'running')"
        ),
    )
    op.create_index(
        "ix_crm_history_import_jobs_status_created",
        "crm_history_import_jobs",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_crm_history_import_jobs_workspace_lead_created",
        "crm_history_import_jobs",
        ["workspace_id", "lead_id", "created_at"],
    )

    op.create_table(
        "crm_history_import_events",
        sa.Column("import_event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column("import_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("leads.lead_id"),
            nullable=False,
        ),
        sa.Column("external_activity_id", sa.String(255)),
        sa.Column("fingerprint", sa.String(128), nullable=False),
        sa.Column("activity_type", sa.String(100), nullable=False),
        sa.Column("direction", sa.String(50)),
        sa.Column("content", sa.Text()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_agent_id", sa.String(255)),
        sa.Column("actor_name", sa.String(255)),
        sa.Column(
            "details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "import_job_id"],
            [
                "crm_history_import_jobs.workspace_id",
                "crm_history_import_jobs.import_job_id",
            ],
            name="fk_crm_history_import_events_workspace_job",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "import_job_id",
            "fingerprint",
            name="uq_crm_history_import_events_workspace_job_fingerprint",
        ),
    )
    op.create_index(
        "ix_crm_history_import_events_workspace_job_status",
        "crm_history_import_events",
        ["workspace_id", "import_job_id", "status"],
    )
    op.create_index(
        "ix_crm_history_import_events_workspace_lead_occurred",
        "crm_history_import_events",
        ["workspace_id", "lead_id", "occurred_at"],
    )
    for table_name in _TABLES:
        _enable_workspace_rls(table_name)


def downgrade() -> None:
    for table_name in reversed(_TABLES):
        _disable_workspace_rls(table_name)
    op.drop_table("crm_history_import_events")
    op.drop_table("crm_history_import_jobs")


def _enable_workspace_rls(table_name: str) -> None:
    policy_name = f"rls_{table_name}_workspace_isolation"
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
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
    policy_name = f"rls_{table_name}_workspace_isolation"
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"')
    op.execute(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')