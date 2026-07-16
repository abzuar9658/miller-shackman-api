"""add leads primary phone index

Revision ID: 0024_add_leads_primary_phone_index
Revises: 0023_create_inbound_message_crm_completions
Create Date: 2026-07-16 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024_add_leads_primary_phone_index"
down_revision: str | None = "0023_create_inbound_message_crm_completions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_leads_workspace_primary_phone",
        "leads",
        ["workspace_id", "primary_phone"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_leads_workspace_primary_phone", table_name="leads")
