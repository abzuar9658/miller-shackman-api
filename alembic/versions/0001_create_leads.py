"""create leads table

Revision ID: 0001_create_leads
Revises:
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_create_leads"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crm_provider", sa.String(length=50), nullable=False),
        sa.Column("crm_lead_id", sa.String(length=255), nullable=False),
        sa.Column("source_payload_version", sa.String(length=100), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("facts_derived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assigned_agent_crm_id", sa.String(length=255), nullable=True),
        sa.Column("assigned_agent_name_present", sa.Boolean(), nullable=False),
        sa.Column("has_accountable_owner", sa.Boolean(), nullable=False),
        sa.Column("ownership_last_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lead_type", sa.String(length=50), nullable=False),
        sa.Column("classification_reason", sa.String(length=100), nullable=False),
        sa.Column("crm_type_raw", sa.String(length=255), nullable=True),
        sa.Column("lead_source", sa.String(length=255), nullable=False),
        sa.Column("lead_stage", sa.String(length=255), nullable=False),
        sa.Column("created_via", sa.String(length=255), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("mapped_custom_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("has_email", sa.Boolean(), nullable=False),
        sa.Column("has_phone", sa.Boolean(), nullable=False),
        sa.Column("has_sms_capable_phone", sa.Boolean(), nullable=False),
        sa.Column("email_count", sa.Integer(), nullable=False),
        sa.Column("phone_count", sa.Integer(), nullable=False),
        sa.Column("sms_permission_status", sa.String(length=50), nullable=False),
        sa.Column("email_permission_status", sa.String(length=50), nullable=False),
        sa.Column("sms_opted_out", sa.Boolean(), nullable=False),
        sa.Column("email_unsubscribed", sa.Boolean(), nullable=False),
        sa.Column("do_not_contact", sa.Boolean(), nullable=True),
        sa.Column("suppression_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("permission_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("crm_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("crm_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_meaningful_communication_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_agent_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contacted_count", sa.Integer(), nullable=True),
        sa.Column("activity_reliability", sa.String(length=50), nullable=False),
        sa.Column("latest_property_event_type", sa.String(length=50), nullable=True),
        sa.Column("latest_property_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_property_price_band", sa.String(length=50), nullable=True),
        sa.Column("latest_property_context_present", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("lead_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "crm_provider",
            "crm_lead_id",
            name="uq_leads_workspace_crm_identity",
        ),
    )
    op.create_index("ix_leads_workspace_lead_type", "leads", ["workspace_id", "lead_type"])
    op.create_index(
        "ix_leads_workspace_last_meaningful",
        "leads",
        ["workspace_id", "last_meaningful_communication_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_leads_workspace_last_meaningful", table_name="leads")
    op.drop_index("ix_leads_workspace_lead_type", table_name="leads")
    op.drop_table("leads")
