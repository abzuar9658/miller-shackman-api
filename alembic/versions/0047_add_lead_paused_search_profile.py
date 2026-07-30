"""add lead paused search profile

Revision ID: 0047_add_lead_paused_search_profile
Revises: 0046_add_outbound_crm_conversation_publish_timestamp
Create Date: 2026-07-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0047_add_lead_paused_search_profile"
down_revision: str | None = "0046_add_outbound_crm_conversation_publish_timestamp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("paused_search_active", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("leads", sa.Column("pause_reason_code", sa.String(length=100), nullable=True))
    op.add_column("leads", sa.Column("pause_reason_note", sa.Text(), nullable=True))
    op.add_column(
        "leads",
        sa.Column("reengagement_not_before", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("reengagement_window_label", sa.String(length=100), nullable=True),
    )
    op.add_column("leads", sa.Column("paused_search_source", sa.String(length=100), nullable=True))
    op.add_column(
        "leads",
        sa.Column("paused_search_recorded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column(
            "paused_search_recorded_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=True,
        ),
    )
    op.add_column(
        "leads",
        sa.Column("paused_search_last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_leads_workspace_paused_search_active",
        "leads",
        ["workspace_id", "paused_search_active"],
    )

    op.create_table(
        "lead_paused_search_history",
        sa.Column("history_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
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
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("previous_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("previous_reason_code", sa.String(length=100), nullable=True),
        sa.Column("previous_reason_note", sa.Text(), nullable=True),
        sa.Column("previous_reengagement_not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_reengagement_window_label", sa.String(length=100), nullable=True),
        sa.Column("previous_source", sa.String(length=100), nullable=True),
        sa.Column("previous_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "previous_recorded_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=True,
        ),
        sa.Column("previous_last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("current_reason_code", sa.String(length=100), nullable=True),
        sa.Column("current_reason_note", sa.Text(), nullable=True),
        sa.Column("current_reengagement_not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_reengagement_window_label", sa.String(length=100), nullable=True),
        sa.Column("current_source", sa.String(length=100), nullable=True),
        sa.Column("current_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "current_recorded_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=True,
        ),
        sa.Column("current_last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_lead_paused_search_history_workspace_lead_created",
        "lead_paused_search_history",
        ["workspace_id", "lead_id", "created_at"],
    )
    _enable_workspace_rls("lead_paused_search_history")


def downgrade() -> None:
    _disable_workspace_rls("lead_paused_search_history")
    op.drop_index(
        "ix_lead_paused_search_history_workspace_lead_created",
        table_name="lead_paused_search_history",
    )
    op.drop_table("lead_paused_search_history")
    op.drop_index("ix_leads_workspace_paused_search_active", table_name="leads")
    op.drop_column("leads", "paused_search_last_confirmed_at")
    op.drop_column("leads", "paused_search_recorded_by_user_id")
    op.drop_column("leads", "paused_search_recorded_at")
    op.drop_column("leads", "paused_search_source")
    op.drop_column("leads", "reengagement_window_label")
    op.drop_column("leads", "reengagement_not_before")
    op.drop_column("leads", "pause_reason_note")
    op.drop_column("leads", "pause_reason_code")
    op.drop_column("leads", "paused_search_active")


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