"""align preflight digest schema with batch aggregate

Revision ID: 0013_align_preflight_digest_schema
Revises: 0012_handoff_completion_and_workspace_handoff_config
Create Date: 2026-07-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013_align_preflight_digest_schema"
down_revision: str | None = "0012_handoff_completion_and_workspace_handoff_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "preflight_digests_recipient_user_id_fkey",
        "preflight_digests",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_preflight_digests_workspace_campaign_batch_recipient",
        "preflight_digests",
        type_="unique",
    )
    op.drop_constraint(
        "uq_preflight_digests_workspace_idempotency",
        "preflight_digests",
        type_="unique",
    )
    op.drop_index("ix_preflight_digests_workspace_status", table_name="preflight_digests")

    op.drop_column("preflight_digests", "recipient_user_id")
    op.drop_column("preflight_digests", "provider_reference")
    op.drop_column("preflight_digests", "idempotency_key")

    op.alter_column(
        "preflight_digests",
        "veto_window_expires_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )

    op.add_column(
        "preflight_digests",
        sa.Column(
            "entries",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "preflight_digests",
        sa.Column(
            "notification_records",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    op.create_unique_constraint(
        "uq_preflight_digests_workspace_campaign_batch",
        "preflight_digests",
        ["workspace_id", "campaign_id", "batch_id"],
    )
    op.create_index(
        "ix_preflight_digests_workspace_status",
        "preflight_digests",
        ["workspace_id", "status"],
    )

    op.add_column(
        "preflight_vetoes",
        sa.Column("digest_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "preflight_vetoes_digest_id_fkey",
        "preflight_vetoes",
        "preflight_digests",
        ["digest_id"],
        ["digest_id"],
    )
    op.create_index(
        "ix_preflight_vetoes_digest_id",
        "preflight_vetoes",
        ["digest_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_preflight_vetoes_digest_id", table_name="preflight_vetoes")
    op.drop_constraint("preflight_vetoes_digest_id_fkey", "preflight_vetoes", type_="foreignkey")
    op.drop_column("preflight_vetoes", "digest_id")

    op.drop_index("ix_preflight_digests_workspace_status", table_name="preflight_digests")
    op.drop_constraint(
        "uq_preflight_digests_workspace_campaign_batch",
        "preflight_digests",
        type_="unique",
    )
    op.drop_column("preflight_digests", "notification_records")
    op.drop_column("preflight_digests", "entries")

    op.alter_column(
        "preflight_digests",
        "veto_window_expires_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )

    op.add_column(
        "preflight_digests",
        sa.Column(
            "recipient_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "preflight_digests",
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "preflight_digests",
        sa.Column("idempotency_key", sa.String(length=500), nullable=True),
    )

    op.create_foreign_key(
        "preflight_digests_recipient_user_id_fkey",
        "preflight_digests",
        "users",
        ["recipient_user_id"],
        ["user_id"],
    )
    op.create_unique_constraint(
        "uq_preflight_digests_workspace_campaign_batch_recipient",
        "preflight_digests",
        ["workspace_id", "campaign_id", "batch_id", "recipient_user_id"],
    )
    op.create_unique_constraint(
        "uq_preflight_digests_workspace_idempotency",
        "preflight_digests",
        ["workspace_id", "idempotency_key"],
    )
    op.create_index(
        "ix_preflight_digests_workspace_status",
        "preflight_digests",
        ["workspace_id", "status"],
    )
