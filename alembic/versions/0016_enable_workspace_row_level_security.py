"""enable workspace row-level security

Revision ID: 0016_enable_workspace_row_level_security
Revises: 0015_create_campaign_admin_audit_logs
Create Date: 2026-07-12 00:00:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0016_enable_workspace_row_level_security"
down_revision = "0015_campaign_admin_audit_logs"
branch_labels = None
depends_on = None

_RLS_TABLES = (
    "leads",
    "outbound_messages",
    "campaigns",
    "campaign_versions",
    "campaign_cadence_steps",
    "campaign_admin_audit_logs",
    "crm_sync_jobs",
    "external_events",
    "provider_message_events",
    "outbox_events",
    "preflight_digests",
    "preflight_vetoes",
    "conversations",
    "inbound_messages",
    "conversation_summaries",
    "handoffs",
    "handoff_completions",
    "workspace_contact_policies",
    "workspace_handoff_configs",
    "campaign_enrollments",
    "lead_workflows",
    "workflow_transitions",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_current_workspace_id() RETURNS uuid
        LANGUAGE sql STABLE AS $$
            SELECT CAST(NULLIF(current_setting('app.current_workspace_id', true), '') AS uuid)
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_rls_service_access_enabled() RETURNS boolean
        LANGUAGE sql STABLE AS $$
            SELECT COALESCE(NULLIF(current_setting('app.service_access', true), ''), 'off') = 'on'
        $$;
        """
    )

    for table_name in _RLS_TABLES:
        _enable_workspace_rls(table_name)


def downgrade() -> None:
    for table_name in reversed(_RLS_TABLES):
        _disable_workspace_rls(table_name)

    op.execute("DROP FUNCTION IF EXISTS app_rls_service_access_enabled()")
    op.execute("DROP FUNCTION IF EXISTS app_current_workspace_id()")


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
