"""add paused-search policy contract fields

Revision ID: 0082_add_paused_search_policy_contract
Revises: 0081_add_paused_search_step_template_profiles
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0082_add_paused_search_policy_contract"
down_revision: str | None = "0081_add_paused_search_step_template_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    version_defaults = (
        ("track_mode", sa.String(length=50), sa.text("'custom_bounded'")),
        ("interim_contact_policy", sa.String(length=80), sa.text("'not_allowed'")),
        ("reply_policy", sa.String(length=50), sa.text("'end'")),
        ("channel_sequence", sa.String(length=20), sa.text("'sequential'")),
        ("max_cycles", sa.Integer(), sa.text("1")),
        ("max_ai_interactions", sa.Integer(), sa.text("5")),
    )
    for name, column_type, default in version_defaults:
        op.add_column(
            "paused_search_track_versions",
            sa.Column(name, column_type, nullable=False, server_default=default),
        )
        op.alter_column(
            "paused_search_track_versions",
            name,
            server_default=None,
        )

    op.add_column(
        "paused_search_track_steps",
        sa.Column("action", sa.String(length=20), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE paused_search_track_steps
            SET action = CASE WHEN review_required THEN 'review' ELSE 'send' END
            WHERE action IS NULL
            """
        )
    )
    op.alter_column("paused_search_track_steps", "action", nullable=False)


def downgrade() -> None:
    op.drop_column("paused_search_track_steps", "action")
    for name in (
        "max_ai_interactions",
        "max_cycles",
        "channel_sequence",
        "reply_policy",
        "interim_contact_policy",
        "track_mode",
    ):
        op.drop_column("paused_search_track_versions", name)