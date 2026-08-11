"""add paused-search channel writing purposes

Revision ID: 0090_add_paused_search_writing_purposes
Revises: 0089_create_outbound_send_requests
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0090_add_paused_search_writing_purposes"
down_revision: str | None = "0089_create_outbound_send_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EMAIL_DEFAULT = (
    "Write a track-specific paused-search email that acknowledges the lead's stated "
    "reason for waiting and asks one low-pressure question."
)
SMS_DEFAULT = (
    "Write a concise track-specific paused-search SMS that acknowledges the lead's "
    "stated reason for waiting and invites a brief reply."
)


def upgrade() -> None:
    op.add_column(
        "paused_search_track_versions",
        sa.Column("email_writing_purpose", sa.Text(), nullable=True),
    )
    op.add_column(
        "paused_search_track_versions",
        sa.Column("sms_writing_purpose", sa.Text(), nullable=True),
    )
    op.execute(
        sa.text("UPDATE paused_search_track_versions SET email_writing_purpose = :purpose")
        .bindparams(purpose=EMAIL_DEFAULT)
    )
    op.execute(
        sa.text("UPDATE paused_search_track_versions SET sms_writing_purpose = :purpose")
        .bindparams(purpose=SMS_DEFAULT)
    )
    op.alter_column("paused_search_track_versions", "email_writing_purpose", nullable=False)
    op.alter_column("paused_search_track_versions", "sms_writing_purpose", nullable=False)


def downgrade() -> None:
    op.drop_column("paused_search_track_versions", "sms_writing_purpose")
    op.drop_column("paused_search_track_versions", "email_writing_purpose")
