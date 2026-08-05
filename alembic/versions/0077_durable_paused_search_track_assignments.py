"""add durable paused-search track assignments

Revision ID: 0077_durable_paused_search_track_assignments
Revises: 0076_preserve_paused_track_delete_audit
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0077_durable_paused_search_track_assignments"
down_revision: str | None = "0076_preserve_paused_track_delete_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "paused_search_track_assignments"
_ACTIVE_LEAD_INDEX = "uq_paused_search_track_assignments_active_lead"
_ACTIVE_TRACK_INDEX = "ix_paused_search_track_assignments_active_track"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("assignment_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("leads.lead_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "track_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("paused_search_tracks.track_id", ondelete="SET NULL"),
        ),
        sa.Column(
            "track_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("paused_search_track_versions.track_version_id", ondelete="SET NULL"),
        ),
        sa.Column("track_key_snapshot", sa.String(255), nullable=False),
        sa.Column("track_name_snapshot", sa.String(255), nullable=False),
        sa.Column("track_version_snapshot", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column(
            "assigned_by_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
        ),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column(
            "released_by_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
        ),
        sa.Column("release_reason", sa.Text()),
    )
    op.create_index(
        _ACTIVE_LEAD_INDEX,
        _TABLE,
        ["workspace_id", "lead_id"],
        unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
    )
    op.create_index(
        _ACTIVE_TRACK_INDEX,
        _TABLE,
        ["workspace_id", "track_id"],
        postgresql_where=sa.text("released_at IS NULL"),
    )
    _enable_workspace_rls()


def downgrade() -> None:
    _disable_workspace_rls()
    op.drop_table(_TABLE)


def _enable_workspace_rls() -> None:
    policy_name = f"rls_{_TABLE}_workspace_isolation"
    op.execute(f'ALTER TABLE "{_TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{_TABLE}" FORCE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{_TABLE}"')
    op.execute(
        f'''
        CREATE POLICY "{policy_name}" ON "{_TABLE}"
        USING (app_rls_service_access_enabled() OR workspace_id = app_current_workspace_id())
        WITH CHECK (app_rls_service_access_enabled() OR workspace_id = app_current_workspace_id())
        '''
    )


def _disable_workspace_rls() -> None:
    policy_name = f"rls_{_TABLE}_workspace_isolation"
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{_TABLE}"')
    op.execute(f'ALTER TABLE "{_TABLE}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{_TABLE}" DISABLE ROW LEVEL SECURITY')