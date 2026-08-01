from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class TemplateChannel(StrEnum):
    SMS = "sms"
    EMAIL = "email"


class TemplateStatus(StrEnum):
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class TemplateValidationError(StrEnum):
    EMPTY_KEY = "empty_key"
    INVALID_VERSION = "invalid_version"
    EMPTY_CONTENT = "empty_content"
    EMPTY_PURPOSE = "empty_purpose"
    UNSUPPORTED_VARIABLE = "unsupported_variable"
    CHANNEL_MISMATCH = "channel_mismatch"
    MISSING_SAFETY_TAG = "missing_safety_tag"


ALLOWED_TEMPLATE_VARIABLES = frozenset(
    {
        "agent_name",
        "brokerage_name",
        "lead_first_name",
        "message_body",
        "message_subject",
    }
)


@dataclass(frozen=True)
class TemplateVersion:
    template_version_id: UUID
    workspace_id: UUID
    template_key: str
    version: int
    channel: TemplateChannel
    purpose: str
    content: str
    subject: str | None
    prompt_text: str | None
    allowed_variables: tuple[str, ...]
    permitted_use_tags: tuple[str, ...]
    status: TemplateStatus
    approved_at: datetime
    created_at: datetime


def validate_template_version(
    template: TemplateVersion,
) -> tuple[TemplateValidationError, ...]:
    errors: list[TemplateValidationError] = []
    if not template.template_key.strip():
        errors.append(TemplateValidationError.EMPTY_KEY)
    if template.version < 1:
        errors.append(TemplateValidationError.INVALID_VERSION)
    if not template.content.strip():
        errors.append(TemplateValidationError.EMPTY_CONTENT)
    if not template.purpose.strip():
        errors.append(TemplateValidationError.EMPTY_PURPOSE)
    if any(variable not in ALLOWED_TEMPLATE_VARIABLES for variable in template.allowed_variables):
        errors.append(TemplateValidationError.UNSUPPORTED_VARIABLE)
    if template.channel is TemplateChannel.EMAIL and not template.subject:
        errors.append(TemplateValidationError.CHANNEL_MISMATCH)
    if template.channel is TemplateChannel.SMS and template.subject:
        errors.append(TemplateValidationError.CHANNEL_MISMATCH)
    if template.status is TemplateStatus.APPROVED and not template.permitted_use_tags:
        errors.append(TemplateValidationError.MISSING_SAFETY_TAG)
    return tuple(errors)
