"""add campaign crm enrollment tag

Revision ID: 0018
Revises: 0017_crm_sync_active_guard
Create Date: 2026-07-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017_crm_sync_active_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaign_versions",
        sa.Column("crm_enrollment_tag", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("campaign_versions", "crm_enrollment_tag")
