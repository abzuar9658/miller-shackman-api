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
        sa.Column("reason_code", sa.String(100)),
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
    op.execute("SELECT set_config('app.service_access', 'on', true)")
    _backfill_latest_workflow_pins()
    _backfill_unambiguous_legacy_reasons()
    _enable_workspace_rls()


def downgrade() -> None:
    _disable_workspace_rls()
    op.drop_table(_TABLE)


def _backfill_latest_workflow_pins() -> None:
    op.execute(
        sa.text(
            """
            WITH ranked_workflow_pins AS (
                SELECT
                    workflow.workspace_id,
                    workflow.lead_id,
                    workflow.paused_search_track_version_id,
                    workflow.updated_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY workflow.workspace_id, workflow.lead_id
                        ORDER BY workflow.updated_at DESC, workflow.created_at DESC,
                                 workflow.workflow_id DESC
                    ) AS pin_rank
                FROM lead_workflows AS workflow
                JOIN leads AS lead
                  ON lead.workspace_id = workflow.workspace_id
                 AND lead.lead_id = workflow.lead_id
                WHERE lead.paused_search_active IS TRUE
                  AND workflow.paused_search_track_version_id IS NOT NULL
            )
            INSERT INTO paused_search_track_assignments (
                assignment_id, workspace_id, lead_id, track_id, track_version_id,
                track_key_snapshot, track_name_snapshot, track_version_snapshot,
                reason_code, source, assigned_by_user_id, assigned_at
            )
            SELECT
                gen_random_uuid(), lead.workspace_id, lead.lead_id, track.track_id,
                version.track_version_id, track.track_key, track.display_name,
                version.version_number, lead.pause_reason_code, 'workflow_backfill',
                lead.paused_search_recorded_by_user_id,
                COALESCE(lead.paused_search_recorded_at, pin.updated_at, lead.updated_at)
            FROM leads AS lead
            JOIN ranked_workflow_pins AS pin
              ON pin.workspace_id = lead.workspace_id
             AND pin.lead_id = lead.lead_id
             AND pin.pin_rank = 1
            JOIN paused_search_track_versions AS version
              ON version.workspace_id = pin.workspace_id
             AND version.track_version_id = pin.paused_search_track_version_id
            JOIN paused_search_tracks AS track
              ON track.workspace_id = version.workspace_id
             AND track.track_id = version.track_id
            WHERE lead.paused_search_active IS TRUE
            """
        )
    )


def _backfill_unambiguous_legacy_reasons() -> None:
    op.execute(
        sa.text(
            """
            WITH reason_track_history AS (
                SELECT version.workspace_id, reason.reason_code, version.track_id
                FROM paused_search_track_versions AS version
                CROSS JOIN LATERAL jsonb_array_elements_text(
                    version.default_for_reason_codes
                ) AS reason(reason_code)
            ),
            unique_reason_tracks AS (
                SELECT workspace_id, reason_code, MIN(track_id::text)::uuid AS track_id
                FROM reason_track_history
                GROUP BY workspace_id, reason_code
                HAVING COUNT(DISTINCT track_id) = 1
            ),
            ranked_versions AS (
                SELECT version.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY version.workspace_id, version.track_id
                           ORDER BY version.version_number DESC, version.created_at DESC,
                                    version.track_version_id DESC
                       ) AS version_rank
                FROM paused_search_track_versions AS version
            )
            INSERT INTO paused_search_track_assignments (
                assignment_id, workspace_id, lead_id, track_id, track_version_id,
                track_key_snapshot, track_name_snapshot, track_version_snapshot,
                reason_code, source, assigned_by_user_id, assigned_at
            )
            SELECT
                gen_random_uuid(), lead.workspace_id, lead.lead_id, track.track_id,
                version.track_version_id, track.track_key, track.display_name,
                version.version_number, lead.pause_reason_code, 'legacy_reason_backfill',
                lead.paused_search_recorded_by_user_id,
                COALESCE(lead.paused_search_recorded_at, lead.updated_at)
            FROM leads AS lead
            JOIN unique_reason_tracks AS reason_track
              ON reason_track.workspace_id = lead.workspace_id
             AND reason_track.reason_code = lead.pause_reason_code
            JOIN ranked_versions AS version
              ON version.workspace_id = reason_track.workspace_id
             AND version.track_id = reason_track.track_id
             AND version.version_rank = 1
            JOIN paused_search_tracks AS track
              ON track.workspace_id = version.workspace_id
             AND track.track_id = version.track_id
            WHERE lead.paused_search_active IS TRUE
              AND NOT EXISTS (
                  SELECT 1
                  FROM paused_search_track_assignments AS assignment
                  WHERE assignment.workspace_id = lead.workspace_id
                    AND assignment.lead_id = lead.lead_id
                    AND assignment.released_at IS NULL
              )
            """
        )
    )


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