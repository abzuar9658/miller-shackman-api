"""add email subject template to outbound drafting config

Revision ID: 0033_add_email_subject_template_to_outbound_drafting
Revises: 0032_create_workspace_outbound_drafting_config_table
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0033_add_email_subject_template_to_outbound_drafting"
down_revision: str | None = "0032_create_workspace_outbound_drafting_config_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_SUBJECT_TEMPLATE = "{{message_subject}}"


def upgrade() -> None:
    op.add_column(
        "workspace_outbound_drafting_configs",
        sa.Column(
            "email_subject_template",
            sa.Text(),
            nullable=False,
            server_default=_DEFAULT_SUBJECT_TEMPLATE,
        ),
    )
    op.alter_column(
        "workspace_outbound_drafting_configs",
        "email_subject_template",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column(
        "workspace_outbound_drafting_configs",
        "email_subject_template",
    )
