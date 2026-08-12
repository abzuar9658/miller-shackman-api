from typing import cast

from pydantic import SecretStr

from app.application.ports.auth import AccessTokenService, OpaqueTokenService, PasswordHasher
from app.application.ports.cache import CacheProvider
from app.application.ports.crm import CRMClient
from app.application.ports.crm_sync import CanonicalLeadSnapshotSource
from app.application.ports.listing_search import ListingSearchClient
from app.application.ports.llm import LLMClient
from app.application.ports.messaging import EmailProvider, SMSProvider
from app.application.ports.notifications import NotificationProvider
from app.application.ports.storage import FileStorageProvider
from app.application.ports.temporal import LeadNurtureWorkflowSignaler, TemporalWorkflowStarter
from app.core.config import Settings, get_settings
from app.infrastructure.auth.passwords import PasslibPasswordHasher
from app.infrastructure.auth.tokens import JoseAccessTokenService, SecureOpaqueTokenService


def _secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value else None


def build_crm_client(settings: Settings | None = None) -> CRMClient:
    settings = settings or get_settings()
    if settings.crm_provider == "follow_up_boss":
        from app.infrastructure.crm.follow_up_boss import FollowUpBossCRMClient

        api_key = _secret(settings.fub_api_key)
        if not api_key:
            raise ValueError("FUB_API_KEY is required")
        return FollowUpBossCRMClient(
            api_key=api_key,
            base_url=settings.fub_base_url,
            inbox_sync_enabled=settings.fub_inbox_sync_enabled,
            inbox_app_id=settings.fub_inbox_app_id or None,
            inbox_sender_name=settings.fub_inbox_sender_name,
        )
    raise ValueError(f"Unsupported CRM provider: {settings.crm_provider}")


def build_crm_lead_snapshot_source(settings: Settings | None = None) -> CanonicalLeadSnapshotSource:
    return cast(CanonicalLeadSnapshotSource, build_crm_client(settings))


def build_llm_client(settings: Settings | None = None) -> LLMClient:
    settings = settings or get_settings()
    from app.domain.llm import LLMProviderKind
    from app.infrastructure.llm.routing import RoutingLLMClient

    try:
        default_provider = LLMProviderKind(settings.llm_provider)
    except ValueError:
        raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}") from None
    if default_provider is LLMProviderKind.BEDROCK and not settings.bedrock_enabled:
        raise ValueError("LLM_PROVIDER is 'bedrock' but BEDROCK_ENABLED is false")

    clients: dict[LLMProviderKind, LLMClient] = {}

    api_key = _secret(settings.openrouter_api_key)
    if not api_key and default_provider is LLMProviderKind.OPENROUTER:
        raise ValueError("OPENROUTER_API_KEY is required")
    if api_key:
        from app.infrastructure.llm.openrouter import OpenRouterLLMClient

        clients[LLMProviderKind.OPENROUTER] = OpenRouterLLMClient(
            api_key=api_key,
            base_url=settings.openrouter_base_url,
            model=settings.openrouter_model,
            drafting_model=settings.resolved_openrouter_drafting_model,
            classification_model=settings.resolved_openrouter_classification_model,
        )

    if settings.bedrock_enabled:
        from app.infrastructure.llm.bedrock import BedrockLLMClient

        clients[LLMProviderKind.BEDROCK] = BedrockLLMClient(
            region=settings.bedrock_region,
            drafting_model=settings.bedrock_drafting_model,
            classification_model=settings.bedrock_classification_model,
            aws_access_key_id=_secret(settings.bedrock_access_key_id),
            aws_secret_access_key=_secret(settings.bedrock_secret_access_key),
            aws_session_token=_secret(settings.bedrock_session_token),
        )

    return RoutingLLMClient(default_provider=default_provider, clients=clients)


def build_sms_provider(settings: Settings | None = None) -> SMSProvider:
    settings = settings or get_settings()
    if settings.sms_provider == "twilio":
        from app.infrastructure.messaging.twilio import TwilioSMSProvider

        account_sid = _secret(settings.twilio_account_sid)
        auth_token = _secret(settings.twilio_auth_token)
        if not account_sid or not auth_token:
            raise ValueError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are required")
        return TwilioSMSProvider(
            account_sid=account_sid,
            auth_token=auth_token,
            from_phone=settings.twilio_from_phone,
        )
    if settings.sms_provider == "sink":
        from app.infrastructure.messaging.sink import SinkSMSProvider

        return SinkSMSProvider()
    raise ValueError(f"Unsupported SMS provider: {settings.sms_provider}")


def build_email_provider(settings: Settings | None = None) -> EmailProvider:
    settings = settings or get_settings()
    from_email = settings.email_from_email or settings.sendgrid_from_email

    if settings.email_provider == "sendgrid":
        from app.infrastructure.messaging.sendgrid import SendGridEmailProvider

        api_key = _secret(settings.sendgrid_api_key)
        if not api_key:
            raise ValueError("SENDGRID_API_KEY is required")
        return SendGridEmailProvider(
            api_key=api_key,
            from_email=settings.sendgrid_from_email or settings.email_from_email,
        )
    if settings.email_provider == "mailgun":
        from app.infrastructure.messaging.mailgun import MailgunEmailProvider

        api_key = _secret(settings.mailgun_api_key)
        if not api_key:
            raise ValueError("MAILGUN_API_KEY is required")
        if not settings.mailgun_domain:
            raise ValueError("MAILGUN_DOMAIN is required")
        if not from_email:
            raise ValueError(
                "EMAIL_FROM_EMAIL or SENDGRID_FROM_EMAIL is required for EMAIL_PROVIDER=mailgun"
            )
        return MailgunEmailProvider(
            api_key=api_key,
            domain=settings.mailgun_domain,
            from_email=from_email,
        )
    if settings.email_provider == "mailpit":
        from app.infrastructure.messaging.mailpit import MailpitEmailProvider

        if not from_email:
            raise ValueError(
                "EMAIL_FROM_EMAIL or SENDGRID_FROM_EMAIL is required for EMAIL_PROVIDER=mailpit"
            )
        return MailpitEmailProvider(
            smtp_host=settings.mailpit_smtp_host,
            smtp_port=settings.mailpit_smtp_port,
            from_email=from_email,
        )
    if settings.email_provider == "sink":
        from app.infrastructure.messaging.sink import SinkEmailProvider

        return SinkEmailProvider()
    raise ValueError(f"Unsupported email provider: {settings.email_provider}")


def build_notification_provider(settings: Settings | None = None) -> NotificationProvider:
    from app.infrastructure.notifications import EmailNotificationProvider

    return EmailNotificationProvider(build_email_provider(settings))


def build_storage_provider(settings: Settings | None = None) -> FileStorageProvider:
    settings = settings or get_settings()
    if settings.storage_provider == "s3":
        from app.infrastructure.storage.s3 import S3StorageProvider

        return S3StorageProvider(
            bucket=settings.s3_bucket,
            region=settings.s3_region,
            aws_access_key_id=_secret(settings.aws_access_key_id),
            aws_secret_access_key=_secret(settings.aws_secret_access_key),
        )
    raise ValueError(f"Unsupported storage provider: {settings.storage_provider}")


def build_cache_provider(settings: Settings | None = None) -> CacheProvider:
    settings = settings or get_settings()
    if settings.cache_provider == "redis":
        from app.infrastructure.cache.redis import RedisCacheProvider

        return RedisCacheProvider(redis_url=settings.redis_url)
    raise ValueError(f"Unsupported cache provider: {settings.cache_provider}")


def build_listing_search_client(settings: Settings | None = None) -> ListingSearchClient:
    settings = settings or get_settings()
    from app.infrastructure.listing_sources.streeteasy import StreetEasyListingSearchClient

    return StreetEasyListingSearchClient(
        timeout_seconds=settings.streeteasy_timeout_seconds,
        user_agent=settings.streeteasy_user_agent,
    )


def build_password_hasher(settings: Settings | None = None) -> PasswordHasher:
    settings = settings or get_settings()
    return PasslibPasswordHasher()


def build_access_token_service(settings: Settings | None = None) -> AccessTokenService:
    settings = settings or get_settings()
    secret = _secret(settings.auth_jwt_secret)
    if not secret:
        raise ValueError("AUTH_JWT_SECRET is required")
    return JoseAccessTokenService(
        secret=secret,
        algorithm=settings.auth_jwt_algorithm,
    )


def build_opaque_token_service(settings: Settings | None = None) -> OpaqueTokenService:
    settings = settings or get_settings()
    return SecureOpaqueTokenService()


async def build_temporal_workflow_starter(
    settings: Settings | None = None,
) -> TemporalWorkflowStarter:
    from app.infrastructure.workflows.temporal.starter import build_temporal_workflow_starter

    return await build_temporal_workflow_starter(settings)


async def build_temporal_workflow_signaler(
    settings: Settings | None = None,
) -> LeadNurtureWorkflowSignaler:
    from app.infrastructure.workflows.temporal.starter import build_temporal_workflow_signaler

    return await build_temporal_workflow_signaler(settings)
