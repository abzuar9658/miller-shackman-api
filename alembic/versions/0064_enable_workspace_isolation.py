"""harden paused-search persistence workspace isolation

Revision ID: 0064_enable_workspace_isolation
Revises: 0063_add_paused_search_reviews_notifications
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0064_enable_workspace_isolation"
down_revision: str | None = "0063_add_paused_search_reviews_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RLS_TABLES = (
    "customer_timing_candidates",
    "template_versions",
    "paused_search_notification_policies",
    "paused_search_reviews",
    "paused_search_notifications",
)


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_paused_search_notification_policies_workspace_id_version",
        "paused_search_notification_policies",
        ["workspace_id", "notification_policy_id", "version"],
    )
    op.create_foreign_key(
        "fk_paused_search_notifications_policy_workspace_version",
        "paused_search_notifications",
        "paused_search_notification_policies",
        ["workspace_id", "policy_id", "policy_version"],
        ["workspace_id", "notification_policy_id", "version"],
    )
    for table_name in _RLS_TABLES:
        _enable_workspace_rls(table_name)


def downgrade() -> None:
    for table_name in reversed(_RLS_TABLES):
        _disable_workspace_rls(table_name)
    op.drop_constraint(
        "fk_paused_search_notifications_policy_workspace_version",
        "paused_search_notifications",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_paused_search_notification_policies_workspace_id_version",
        "paused_search_notification_policies",
        type_="unique",
    )


def _enable_workspace_rls(table_name: str) -> None:
    policy_name = f"rls_{table_name}_workspace_isolation"
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
    policy_name = f"rls_{table_name}_workspace_isolation"
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"')
    op.execute(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')
