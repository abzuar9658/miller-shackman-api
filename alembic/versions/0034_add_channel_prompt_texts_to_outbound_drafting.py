"""add channel prompt texts to outbound drafting config

Revision ID: 0034_add_channel_prompt_texts_to_outbound_drafting
Revises: 0033_add_email_subject_template_to_outbound_drafting
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0034_add_channel_prompt_texts_to_outbound_drafting"
down_revision: str | None = "0033_add_email_subject_template_to_outbound_drafting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_SMS_PROMPT = (
    "Write a short, conversational SMS. Keep it warm, specific, and operationally "
    "safe. Personalize from the approved context, avoid repeating recent outbound "
    "phrasing, and prefer plain, human language over salesy wording."
)
_DEFAULT_EMAIL_PROMPT = (
    "Write a concise follow-up email with a short subject line. Keep it warm, "
    "specific, and operationally safe. Personalize from the approved context, avoid "
    "repeating recent outbound phrasing, and prefer plain, human language over salesy wording."
)
_LEGACY_SMS_TEMPLATE = (
    "Write a short, conversational SMS. Acknowledge the lead's latest request, "
    "use approved listing context only when it is present, and end with a clear "
    "offer to have the assigned agent follow up."
)
_LEGACY_EMAIL_TEMPLATE = (
    "Write a concise follow-up email with a short subject line. Acknowledge the "
    "lead's latest request, use approved listing context only when it is present, "
    "and end with a clear offer to have the assigned agent follow up."
)


def upgrade() -> None:
    op.add_column(
        "workspace_outbound_drafting_configs",
        sa.Column("sms_prompt_text", sa.Text(), nullable=False, server_default=_DEFAULT_SMS_PROMPT),
    )
    op.add_column(
        "workspace_outbound_drafting_configs",
        sa.Column(
            "email_prompt_text",
            sa.Text(),
            nullable=False,
            server_default=_DEFAULT_EMAIL_PROMPT,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE workspace_outbound_drafting_configs
            SET sms_prompt_text = CASE
                WHEN sms_template = :legacy_sms_template THEN :legacy_sms_template
                WHEN trim(prompt_text) <> '' THEN prompt_text
                ELSE :default_sms_prompt
            END,
            email_prompt_text = CASE
                WHEN email_template = :legacy_email_template THEN :legacy_email_template
                WHEN trim(prompt_text) <> '' THEN prompt_text
                ELSE :default_email_prompt
            END
            """
        ).bindparams(
            legacy_sms_template=_LEGACY_SMS_TEMPLATE,
            legacy_email_template=_LEGACY_EMAIL_TEMPLATE,
            default_sms_prompt=_DEFAULT_SMS_PROMPT,
            default_email_prompt=_DEFAULT_EMAIL_PROMPT,
        )
    )
    op.alter_column("workspace_outbound_drafting_configs", "sms_prompt_text", server_default=None)
    op.alter_column("workspace_outbound_drafting_configs", "email_prompt_text", server_default=None)


def downgrade() -> None:
    op.drop_column("workspace_outbound_drafting_configs", "email_prompt_text")
    op.drop_column("workspace_outbound_drafting_configs", "sms_prompt_text")
