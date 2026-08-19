"""add outbound message status detail

Revision ID: 0093_add_outbound_message_status_detail
Revises: 0092_remove_sms_compliance_fields
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0093_add_outbound_message_status_detail"
down_revision: str | None = "0092_remove_sms_compliance_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbound_messages",
        sa.Column("status_detail", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outbound_messages", "status_detail")
