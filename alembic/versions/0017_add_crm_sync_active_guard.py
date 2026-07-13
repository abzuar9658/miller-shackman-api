"""add crm sync active job guard

Revision ID: 0017_crm_sync_active_guard
Revises: 0016_enable_workspace_row_level_security
Create Date: 2026-07-13 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_crm_sync_active_guard"
down_revision: str | None = "0016_enable_workspace_row_level_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_crm_sync_jobs_one_active_workspace_provider",
        "crm_sync_jobs",
        ["workspace_id", "crm_provider"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_crm_sync_jobs_one_active_workspace_provider",
        table_name="crm_sync_jobs",
    )
