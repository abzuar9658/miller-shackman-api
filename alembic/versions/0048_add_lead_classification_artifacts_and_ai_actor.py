"""add lead classification artifacts and allow nullable ai actor

Revision ID: 0048_add_lead_classification_artifacts_and_ai_actor
Revises: 0047_add_lead_paused_search_profile
Create Date: 2026-07-25 00:00:00.000000
"""


import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

# revision identifiers, used by Alembic.
revision = "0048_add_lead_classification_artifacts_and_ai_actor"
down_revision = "0047_add_lead_paused_search_profile"
branch_labels = None
depends_on = None

_RLS_TABLE = "lead_classification_artifacts"


def upgrade() -> None:
    op.create_table(
        _RLS_TABLE,
        sa.Column("artifact_id", pg.UUID(as_uuid=True), primary_key=True),
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
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("outcome", sa.String(100), nullable=False),
        sa.Column("pause_reason_code", sa.String(100), nullable=True),
        sa.Column("reengagement_not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reengagement_window_label", sa.String(100), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("prompt_version", sa.String(255), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("usage_tokens", sa.Integer(), nullable=True),
        sa.Column("applied_status", sa.String(100), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_lead_classification_artifacts_workspace_lead_created",
        _RLS_TABLE,
        ["workspace_id", "lead_id", "created_at"],
    )

    op.alter_column(
        "lead_paused_search_history",
        "actor_user_id",
        existing_type=pg.UUID(as_uuid=True),
        nullable=True,
    )

    _enable_workspace_rls(_RLS_TABLE)


def downgrade() -> None:
    _disable_workspace_rls(_RLS_TABLE)
    op.drop_index(
        "ix_lead_classification_artifacts_workspace_lead_created",
        table_name=_RLS_TABLE,
    )
    op.drop_table(_RLS_TABLE)

    op.alter_column(
        "lead_paused_search_history",
        "actor_user_id",
        existing_type=pg.UUID(as_uuid=True),
        nullable=False,
    )


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
