"""remove sms compliance gate fields

Revision ID: 0092_remove_sms_compliance_fields
Revises: 0091_add_llm_provider_task_models
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0092_remove_sms_compliance_fields"
down_revision: str | None = "0091_add_llm_provider_task_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("workspace_contact_policies", "sms_compliance_state")
    op.drop_column("campaign_versions", "sms_compliance_required")


def downgrade() -> None:
    op.add_column(
        "campaign_versions",
        sa.Column(
            "sms_compliance_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "workspace_contact_policies",
        sa.Column(
            "sms_compliance_state",
            sa.String(length=50),
            nullable=False,
            server_default="approved",
        ),
    )
