"""bind paused-search steps to approved template versions

Revision ID: 0065_bind_paused_search_steps_to_templates
Revises: 0064_enable_workspace_isolation
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0065_bind_paused_search_steps_to_templates"
down_revision: str | None = "0064_enable_workspace_isolation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_template_versions_workspace_id_version_id",
        "template_versions",
        ["workspace_id", "template_version_id"],
    )
    op.add_column(
        "paused_search_track_steps",
        sa.Column("template_version_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_paused_track_steps_template_workspace",
        "paused_search_track_steps",
        "template_versions",
        ["workspace_id", "template_version_id"],
        ["workspace_id", "template_version_id"],
    )
    op.create_index(
        "ix_paused_track_steps_workspace_template_version",
        "paused_search_track_steps",
        ["workspace_id", "template_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_paused_track_steps_workspace_template_version",
        table_name="paused_search_track_steps",
    )
    op.drop_constraint(
        "fk_paused_track_steps_template_workspace",
        "paused_search_track_steps",
        type_="foreignkey",
    )
    op.drop_column("paused_search_track_steps", "template_version_id")
    op.drop_constraint(
        "uq_template_versions_workspace_id_version_id",
        "template_versions",
        type_="unique",
    )
