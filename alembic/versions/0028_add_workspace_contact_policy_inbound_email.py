"""add inbound email address to workspace contact policies

Revision ID: 0028_add_workspace_contact_policy_inbound_email
Revises: 0027_create_workspace_llm_config_table
Create Date: 2026-07-16 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028_add_workspace_contact_policy_inbound_email"
down_revision: str | None = "0027_create_workspace_llm_config_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_contact_policies",
        sa.Column("inbound_email_address", sa.String(length=320), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspace_contact_policies", "inbound_email_address")
