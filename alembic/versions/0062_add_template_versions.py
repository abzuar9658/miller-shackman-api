"""add immutable template versions

Revision ID: 0062_add_template_versions
Revises: 0061_add_customer_timing_candidates
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0062_add_template_versions"
down_revision: str | None = "0061_add_customer_timing_candidates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "template_versions",
        sa.Column("template_version_id", sa.UUID(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("template_key", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text()),
        sa.Column("prompt_text", sa.Text()),
        sa.Column("allowed_variables", sa.JSON(), nullable=False),
        sa.Column("permitted_use_tags", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.UniqueConstraint(
            "workspace_id",
            "template_key",
            "version",
            name="uq_template_versions_workspace_key_version",
        ),
    )
    op.create_index(
        "ix_template_versions_workspace_channel",
        "template_versions",
        ["workspace_id", "channel"],
    )
    op.create_index(
        "ix_template_versions_workspace_status",
        "template_versions",
        ["workspace_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_template_versions_workspace_status", table_name="template_versions")
    op.drop_index("ix_template_versions_workspace_channel", table_name="template_versions")
    op.drop_table("template_versions")
