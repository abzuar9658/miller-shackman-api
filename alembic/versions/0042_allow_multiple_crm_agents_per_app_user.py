"""allow multiple crm agents per app user

Revision ID: 0042_allow_multiple_crm_agents_per_app_user
Revises: 0041_add_lead_assignment_resolution_fields
Create Date: 2026-07-21 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0042_allow_multiple_crm_agents_per_app_user"
down_revision: str | None = "0041_add_lead_assignment_resolution_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "uq_workspace_agent_crm_mappings_active_app_user",
        table_name="workspace_agent_crm_mappings",
    )


def downgrade() -> None:
    op.create_index(
        "uq_workspace_agent_crm_mappings_active_app_user",
        "workspace_agent_crm_mappings",
        ["workspace_id", "app_user_id"],
        unique=True,
        postgresql_where=sa.text(
            "app_user_id IS NOT NULL AND mapping_status IN ('verified', 'overridden')"
        ),
    )