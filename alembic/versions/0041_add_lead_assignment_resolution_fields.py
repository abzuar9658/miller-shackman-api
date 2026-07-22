"""add lead assignment resolution fields

Revision ID: 0041_add_lead_assignment_resolution_fields
Revises: 0040_create_crm_agent_mapping_tables
Create Date: 2026-07-21 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0041_add_lead_assignment_resolution_fields"
down_revision: str | None = "0040_create_crm_agent_mapping_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column(
            "assigned_agent_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "leads",
        sa.Column(
            "effective_owner_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "leads",
        sa.Column("effective_owner_source", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column(
            "assignment_resolution_status",
            sa.String(length=100),
            nullable=False,
            server_default="unresolved",
        ),
    )
    op.add_column(
        "leads",
        sa.Column("assignment_last_resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_leads_assigned_agent_user_id_users",
        "leads",
        "users",
        ["assigned_agent_user_id"],
        ["user_id"],
    )
    op.create_foreign_key(
        "fk_leads_effective_owner_user_id_users",
        "leads",
        "users",
        ["effective_owner_user_id"],
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_leads_effective_owner_user_id_users", "leads", type_="foreignkey")
    op.drop_constraint("fk_leads_assigned_agent_user_id_users", "leads", type_="foreignkey")
    op.drop_column("leads", "assignment_last_resolved_at")
    op.drop_column("leads", "assignment_resolution_status")
    op.drop_column("leads", "effective_owner_source")
    op.drop_column("leads", "effective_owner_user_id")
    op.drop_column("leads", "assigned_agent_user_id")