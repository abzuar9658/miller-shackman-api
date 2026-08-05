"""add drafting config to campaign versions

Revision ID: 0079_add_campaign_version_drafting_config
Revises: 0078_repair_paused_search_template_safety_tags
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0079_add_campaign_version_drafting_config"
down_revision: str | None = "0078_repair_paused_search_template_safety_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_PROMPT_TEXT = (
    "You are an administrative follow-up assistant for a real estate brokerage.\n"
    "Draft one compliant outbound message using only the approved JSON context below."
)
_DEFAULT_SMS_PROMPT_TEXT = (
    "Write a short, conversational SMS body for a real estate lead follow-up. Keep it warm, "
    "specific, and operationally safe. Personalize only from the approved context, avoid "
    "repeating recent outbound phrasing, and prefer plain human language over salesy wording. "
    "Do not add a greeting or sign-off when the template already provides that formatting."
)
_DEFAULT_EMAIL_PROMPT_TEXT = (
    "Write a concise follow-up email body with a short subject line. Keep it warm, specific, "
    "and operationally safe. Personalize only from the approved context, avoid repeating recent "
    "outbound phrasing, and prefer plain human language over salesy wording. Do not add a "
    "greeting, "
    "sign-off, sender name, or brokerage name when the templates already provide that formatting."
)
_DEFAULT_EXTRACTION_FIELDS = (
    "'[\"address\", \"location\", \"keywords\", \"search_type\", \"beds\", "
    "\"min_price\", \"max_price\", \"price_band\"]'::jsonb"
)


def upgrade() -> None:
    columns = (
        sa.Column("prompt_text", sa.Text(), nullable=False, server_default=_DEFAULT_PROMPT_TEXT),
        sa.Column(
            "sms_prompt_text", sa.Text(), nullable=False, server_default=_DEFAULT_SMS_PROMPT_TEXT
        ),
        sa.Column(
            "sms_template",
            sa.Text(),
            nullable=False,
            server_default="Hi there,\n\n{{message_body}}",
        ),
        sa.Column(
            "email_prompt_text",
            sa.Text(),
            nullable=False,
            server_default=_DEFAULT_EMAIL_PROMPT_TEXT,
        ),
        sa.Column(
            "email_template",
            sa.Text(),
            nullable=False,
            server_default="Hi there,\n\n{{message_body}}\n\nBest,\n{{brokerage_name}}",
        ),
        sa.Column(
            "email_subject_template",
            sa.Text(),
            nullable=False,
            server_default="{{message_subject}} | {{brokerage_name}}",
        ),
        sa.Column(
            "enabled_extraction_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(_DEFAULT_EXTRACTION_FIELDS),
        ),
    )
    for column in columns:
        op.add_column("campaign_versions", column)

    op.execute(
        """
        UPDATE campaign_versions AS campaign_version
        SET prompt_text = config.prompt_text,
            sms_prompt_text = config.sms_prompt_text,
            sms_template = config.sms_template,
            email_prompt_text = config.email_prompt_text,
            email_template = config.email_template,
            email_subject_template = config.email_subject_template,
            enabled_extraction_fields = config.enabled_extraction_fields
        FROM workspace_outbound_drafting_configs AS config
        WHERE config.workspace_id = campaign_version.workspace_id
        """
    )


def downgrade() -> None:
    for column_name in (
        "enabled_extraction_fields",
        "email_subject_template",
        "email_template",
        "email_prompt_text",
        "sms_template",
        "sms_prompt_text",
        "prompt_text",
    ):
        op.drop_column("campaign_versions", column_name)