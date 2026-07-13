import pytest

from app.core.config import Settings
from scripts.create_demo_workspace import (
    PRODUCTION_CONFIRM_TEXT,
    DemoSeedOptions,
    DemoSeedSafetyError,
    validate_demo_seed_safety,
)


def test_rejects_non_demo_workspace_name() -> None:
    with pytest.raises(DemoSeedSafetyError, match="Demo workspace name"):
        validate_demo_seed_safety(
            Settings(sms_provider="sink", email_provider="sink"),
            DemoSeedOptions(workspace_name="Miller Schackman"),
        )


def test_rejects_live_message_providers() -> None:
    with pytest.raises(DemoSeedSafetyError, match="SMS_PROVIDER"):
        validate_demo_seed_safety(
            Settings(sms_provider="twilio", email_provider="sink"),
            DemoSeedOptions(),
        )

    with pytest.raises(DemoSeedSafetyError, match="EMAIL_PROVIDER"):
        validate_demo_seed_safety(
            Settings(sms_provider="sink", email_provider="sendgrid"),
            DemoSeedOptions(),
        )


def test_rejects_production_without_explicit_confirmation() -> None:
    with pytest.raises(DemoSeedSafetyError, match="Refusing to seed production"):
        validate_demo_seed_safety(
            Settings(environment="production", sms_provider="sink", email_provider="sink"),
            DemoSeedOptions(allow_production=True, confirm_text="WRONG"),
        )

    validate_demo_seed_safety(
        Settings(environment="production", sms_provider="sink", email_provider="sink"),
        DemoSeedOptions(allow_production=True, confirm_text=PRODUCTION_CONFIRM_TEXT),
    )