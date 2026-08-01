from datetime import UTC, datetime
from uuid import UUID

from app.domain.campaigns.template_registry import (
    TemplateChannel,
    TemplateStatus,
    TemplateValidationError,
    TemplateVersion,
    validate_template_version,
)


def _template(**overrides: object) -> TemplateVersion:
    values: dict[str, object] = {
        "template_version_id": UUID("00000000-0000-0000-0000-000000000601"),
        "workspace_id": UUID("00000000-0000-0000-0000-000000000501"),
        "template_key": "paused-search-example",
        "version": 1,
        "channel": TemplateChannel.EMAIL,
        "purpose": "paused_search",
        "content": "Hi {{lead_first_name}} {{message_body}}",
        "subject": "Checking in",
        "prompt_text": "Write a short check-in.",
        "allowed_variables": ("lead_first_name", "message_body"),
        "permitted_use_tags": ("no_prohibited_advice",),
        "status": TemplateStatus.APPROVED,
        "approved_at": datetime(2026, 1, 1, tzinfo=UTC),
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return TemplateVersion(**values)  # type: ignore[arg-type]


def test_approved_email_template_with_allowed_variables_is_valid() -> None:
    assert validate_template_version(_template()) == ()


def test_template_validation_rejects_unsafe_shape() -> None:
    errors = validate_template_version(
        _template(
            version=0,
            content="",
            subject=None,
            allowed_variables=("unknown",),
            permitted_use_tags=(),
        )
    )

    assert errors == (
        TemplateValidationError.INVALID_VERSION,
        TemplateValidationError.EMPTY_CONTENT,
        TemplateValidationError.UNSUPPORTED_VARIABLE,
        TemplateValidationError.CHANNEL_MISMATCH,
        TemplateValidationError.MISSING_SAFETY_TAG,
    )


def test_sms_template_cannot_have_email_subject() -> None:
    errors = validate_template_version(
        _template(channel=TemplateChannel.SMS, subject="not allowed")
    )

    assert errors == (TemplateValidationError.CHANNEL_MISMATCH,)
