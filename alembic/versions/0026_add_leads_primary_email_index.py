"""add leads primary email index

Revision ID: 0026_add_leads_primary_email_index
Revises: 0025_workspace_crm_sync_config
Create Date: 2026-07-16 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026_add_leads_primary_email_index"
down_revision: str | None = "0025_workspace_crm_sync_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_leads_workspace_primary_email",
        "leads",
        ["workspace_id", "primary_email"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_leads_workspace_primary_email", table_name="leads")