"""add handoff lead acknowledgment config

Revision ID: 0044_add_handoff_lead_acknowledgment_config
Revises: 0043_add_reply_routing_token_to_outbound_messages
Create Date: 2026-07-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0044_add_handoff_lead_acknowledgment_config"
down_revision: str | None = "0043_add_reply_routing_token_to_outbound_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_handoff_configs",
        sa.Column(
            "lead_acknowledgment_sms_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "workspace_handoff_configs",
        sa.Column("lead_acknowledgment_sms_body", sa.String(length=4000), nullable=True),
    )
    op.add_column(
        "workspace_handoff_configs",
        sa.Column(
            "lead_acknowledgment_email_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "workspace_handoff_configs",
        sa.Column("lead_acknowledgment_email_subject", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "workspace_handoff_configs",
        sa.Column("lead_acknowledgment_email_body", sa.String(length=4000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspace_handoff_configs", "lead_acknowledgment_email_body")
    op.drop_column("workspace_handoff_configs", "lead_acknowledgment_email_subject")
    op.drop_column("workspace_handoff_configs", "lead_acknowledgment_email_enabled")
    op.drop_column("workspace_handoff_configs", "lead_acknowledgment_sms_body")
    op.drop_column("workspace_handoff_configs", "lead_acknowledgment_sms_enabled")