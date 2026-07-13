import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.infrastructure.messaging.mailpit import MailpitEmailProvider
from app.infrastructure.messaging.sink import SinkEmailProvider, SinkSMSProvider
from app.infrastructure.providers import (
    build_cache_provider,
    build_crm_client,
    build_email_provider,
    build_llm_client,
    build_sms_provider,
    build_storage_provider,
)


def test_build_crm_client_requires_api_key() -> None:
    settings = Settings(fub_api_key=SecretStr(""))
    with pytest.raises(ValueError, match="FUB_API_KEY"):
        build_crm_client(settings)


def test_build_crm_client_returns_adapter() -> None:
    settings = Settings(fub_api_key=SecretStr("valid"))
    client = build_crm_client(settings)
    assert client.supports_notes is True


def test_build_llm_client_requires_api_key() -> None:
    settings = Settings(openrouter_api_key=SecretStr(""))
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        build_llm_client(settings)


def test_build_sms_provider_requires_credentials() -> None:
    settings = Settings(
        sms_provider="twilio",
        twilio_account_sid=SecretStr("sid"),
        twilio_auth_token=SecretStr(""),
    )
    with pytest.raises(ValueError, match="TWILIO"):
        build_sms_provider(settings)


def test_build_sms_provider_returns_sink_adapter() -> None:
    settings = Settings(sms_provider="sink")
    provider = build_sms_provider(settings)
    assert isinstance(provider, SinkSMSProvider)


def test_build_email_provider_requires_api_key() -> None:
    settings = Settings(email_provider="sendgrid", sendgrid_api_key=SecretStr(""))
    with pytest.raises(ValueError, match="SENDGRID_API_KEY"):
        build_email_provider(settings)


def test_build_email_provider_returns_sink_adapter() -> None:
    settings = Settings(email_provider="sink")
    provider = build_email_provider(settings)
    assert isinstance(provider, SinkEmailProvider)


def test_build_email_provider_requires_from_email_for_mailpit() -> None:
    settings = Settings(email_provider="mailpit", sendgrid_from_email="")
    with pytest.raises(ValueError, match="SENDGRID_FROM_EMAIL"):
        build_email_provider(settings)


def test_build_email_provider_returns_mailpit_adapter() -> None:
    settings = Settings(
        email_provider="mailpit",
        sendgrid_from_email="noreply@example.test",
        mailpit_smtp_host="localhost",
        mailpit_smtp_port=51025,
    )
    provider = build_email_provider(settings)
    assert isinstance(provider, MailpitEmailProvider)


def test_build_storage_provider_returns_s3_adapter() -> None:
    settings = Settings(s3_bucket="bucket")
    provider = build_storage_provider(settings)
    assert provider is not None


def test_build_cache_provider_returns_redis_adapter() -> None:
    settings = Settings(redis_url="redis://localhost:6379/0")
    provider = build_cache_provider(settings)
    assert provider is not None
