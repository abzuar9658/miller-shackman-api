"""preserve paused-search track audit rows when tracks are deleted

Revision ID: 0076_preserve_paused_track_delete_audit
Revises: 0075_add_crm_history_cross_source_idempotency
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0076_preserve_paused_track_delete_audit"
down_revision: str | None = "0075_add_crm_history_cross_source_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE paused_search_track_admin_audit_logs "
        "DROP CONSTRAINT IF EXISTS paused_search_track_admin_audit_logs_track_id_fkey"
    )
    op.execute(
        "ALTER TABLE paused_search_track_admin_audit_logs "
        "DROP CONSTRAINT IF EXISTS paused_search_track_admin_audit_logs_track_version_id_fkey"
    )
    op.alter_column(
        "paused_search_track_admin_audit_logs",
        "track_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_paused_track_audit_track",
        "paused_search_track_admin_audit_logs",
        "paused_search_tracks",
        ["track_id"],
        ["track_id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_paused_track_audit_version",
        "paused_search_track_admin_audit_logs",
        "paused_search_track_versions",
        ["track_version_id"],
        ["track_version_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_paused_track_audit_version",
        "paused_search_track_admin_audit_logs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_paused_track_audit_track",
        "paused_search_track_admin_audit_logs",
        type_="foreignkey",
    )
    op.alter_column(
        "paused_search_track_admin_audit_logs",
        "track_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.create_foreign_key(
        "paused_search_track_admin_audit_logs_track_id_fkey",
        "paused_search_track_admin_audit_logs",
        "paused_search_tracks",
        ["track_id"],
        ["track_id"],
    )
    op.create_foreign_key(
        "paused_search_track_admin_audit_logs_track_version_id_fkey",
        "paused_search_track_admin_audit_logs",
        "paused_search_track_versions",
        ["track_version_id"],
        ["track_version_id"],
    )