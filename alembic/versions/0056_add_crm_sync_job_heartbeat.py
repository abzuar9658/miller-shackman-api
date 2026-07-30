"""add CRM sync job heartbeat

Revision ID: 0056_add_crm_sync_job_heartbeat
Revises: 0055_add_crm_sync_window_state_and_lead_cap
Create Date: 2026-07-27 00:00:01.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0056_add_crm_sync_job_heartbeat"
down_revision: str | None = "0055_add_crm_sync_window_state_and_lead_cap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "crm_sync_jobs",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("crm_sync_jobs", "last_heartbeat_at")