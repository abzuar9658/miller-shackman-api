from functools import lru_cache
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Miller Schackman API"
    app_version: str = "0.1.0"
    environment: str = Field(default="local")
    debug: bool = False
    log_level: str = "INFO"
    metrics_enabled: bool = False
    frontend_app_base_url: str = "http://localhost:5173"

    api_v1_prefix: str = "/api/v1"
    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:55432/miller_schackman"
    database_migration_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:55432/miller_schackman"
    )
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=5, ge=0)
    database_pool_timeout_seconds: float = 30.0
    database_pool_recycle_seconds: int = 1800
    # Server-side guards; 0 disables. Applied per connection via asyncpg
    # server_settings so a hung query or forgotten transaction cannot hold
    # locks indefinitely.
    database_statement_timeout_ms: int = Field(default=60_000, ge=0)
    database_idle_in_transaction_session_timeout_ms: int = Field(default=120_000, ge=0)
    database_lock_timeout_ms: int = Field(default=15_000, ge=0)

    rabbitmq_url: str = "amqp://guest:guest@localhost:55672/"
    crm_sync_exchange_name: str = "miller_schackman.events"
    crm_sync_queue_name: str = "miller_schackman.crm_sync"
    crm_sync_worker_prefetch_count: int = 1
    crm_sync_incremental_interval_seconds: int = 300
    crm_sync_scheduler_poll_seconds: int = 60
    crm_sync_scheduler_workspace_limit: int = 100
    crm_sync_pending_stale_timeout_seconds: int = 600
    crm_sync_running_stale_timeout_seconds: int = 300
    crm_sync_running_heartbeat_interval_seconds: int = 30
    crm_webhook_retry_poll_seconds: int = 5
    crm_webhook_retry_batch_size: int = 10
    inbound_message_worker_poll_seconds: float = 2.0
    inbound_message_worker_batch_size: int = 10
    outbound_send_dispatch_poll_seconds: float = 1.0
    outbound_send_dispatch_batch_size: int = 100
    outbound_send_dispatch_stale_seconds: int = 300
    outbound_send_dispatch_metrics_host: str = "127.0.0.1"
    outbound_send_dispatch_metrics_port: int = Field(default=9101, ge=1, le=65535)
    listing_source_crawl_queue_name: str = "miller_schackman.listing_source_crawl"
    listing_source_crawl_worker_prefetch_count: int = 1
    listing_source_crawl_scheduler_poll_seconds: int = 60
    listing_source_crawl_scheduler_source_limit: int = 100
    temporal_address: str = "localhost:57233"
    temporal_task_queue: str = "miller-schackman-task-queue"
    recurring_paused_search_pilot_workspace_ids: list[UUID] = Field(default_factory=list)

    crm_provider: str = "follow_up_boss"
    fub_api_key: SecretStr | None = None
    fub_base_url: str = "https://api.followupboss.com/v1"
    fub_timeout_seconds: float = 30.0
    # X-System-Key issued at FUB system registration; when set, incoming CRM
    # webhooks must carry a valid FUB-Signature header.
    fub_system_key: SecretStr | None = None
    fub_inbox_sync_enabled: bool = False
    fub_history_import_enabled: bool = False
    fub_inbox_app_id: str = ""
    fub_inbox_sender_name: str = "AI Assistant"

    llm_provider: str = "openrouter"
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: float = 60.0
    openrouter_model: str = "openai/gpt-4o-mini"
    # Empty values fall back to openrouter_model.
    openrouter_drafting_model: str = ""
    openrouter_classification_model: str = ""
    openrouter_allowed_models: list[str] = [
        "openai/gpt-4o-mini",
        "openai/gpt-4o",
        "openai/gpt-4.1-mini",
        "anthropic/claude-sonnet-4.5",
        "anthropic/claude-haiku-4.5",
        "google/gemini-2.5-flash",
    ]

    bedrock_enabled: bool = False
    bedrock_region: str = "us-east-1"
    # Leave credentials unset to use the default AWS credential chain
    # (IAM role in production). Kept separate from the S3 aws_* credentials
    # because the two capabilities need different IAM policies.
    bedrock_access_key_id: SecretStr | None = None
    bedrock_secret_access_key: SecretStr | None = None
    bedrock_session_token: SecretStr | None = None
    bedrock_drafting_model: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    bedrock_classification_model: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    bedrock_allowed_models: list[str] = [
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "us.amazon.nova-pro-v1:0",
        "us.amazon.nova-lite-v1:0",
        "us.meta.llama3-3-70b-instruct-v1:0",
    ]

    # Valid values: "twilio" or "sink" (dev-only, no external calls).
    sms_provider: str = "twilio"
    twilio_account_sid: SecretStr | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_from_phone: str = ""
    twilio_timeout_seconds: float = 15.0

    # Valid values: "sendgrid", "mailgun", "mailpit" (dev SMTP inbox), or "sink".
    email_provider: str = "sendgrid"
    email_from_email: str = ""
    sendgrid_api_key: SecretStr | None = None
    sendgrid_event_webhook_public_key: SecretStr | None = None
    sendgrid_from_email: str = ""
    sendgrid_timeout_seconds: float = 15.0
    mailgun_api_key: SecretStr | None = None
    mailgun_domain: str = ""
    mailgun_webhook_signing_key: SecretStr | None = None
    mailpit_smtp_host: str = "localhost"
    mailpit_smtp_port: int = 51025

    storage_provider: str = "s3"
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    s3_bucket: str = ""
    s3_region: str = "us-east-1"

    cache_provider: str = "redis"
    redis_url: str = "redis://localhost:56379/0"

    listing_context_enrichment_enabled: bool = False
    listing_context_enrichment_max_results: int = 3
    listing_context_enrichment_cache_ttl_minutes: int = 60
    streeteasy_base_url: str = "https://streeteasy.com"
    streeteasy_timeout_seconds: float = 10.0
    streeteasy_user_agent: str = "Mozilla/5.0 (compatible; MillerSchackmanBot/0.1)"

    auth_jwt_secret: SecretStr | None = None
    auth_jwt_algorithm: str = "HS256"
    auth_access_token_ttl_minutes: int = 15
    auth_refresh_token_ttl_days: int = 30
    auth_invitation_token_ttl_days: int = 7
    auth_password_reset_token_ttl_minutes: int = 30
    auth_signin_lockout_max_attempts: int = 5
    auth_signin_lockout_window_minutes: int = 15

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("openrouter_allowed_models", "bedrock_allowed_models")
    @classmethod
    def allowed_models_must_be_non_empty(cls, value: list[str]) -> list[str]:
        normalized = tuple(dict.fromkeys(item.strip() for item in value if item.strip()))
        if not normalized:
            raise ValueError("allowed models list must contain at least one model")
        return list(normalized)

    @model_validator(mode="after")
    def openrouter_model_must_be_allowed(self) -> "Settings":
        if self.openrouter_model not in self.openrouter_allowed_models:
            raise ValueError("openrouter_model must be included in openrouter_allowed_models")
        return self

    @model_validator(mode="after")
    def openrouter_task_models_must_be_allowed(self) -> "Settings":
        for field_name in ("openrouter_drafting_model", "openrouter_classification_model"):
            model = getattr(self, field_name).strip()
            if model and model not in self.openrouter_allowed_models:
                raise ValueError(
                    f"{field_name} must be included in openrouter_allowed_models"
                )
        return self

    @model_validator(mode="after")
    def bedrock_task_models_must_be_allowed(self) -> "Settings":
        for field_name in ("bedrock_drafting_model", "bedrock_classification_model"):
            if getattr(self, field_name) not in self.bedrock_allowed_models:
                raise ValueError(f"{field_name} must be included in bedrock_allowed_models")
        return self

    @property
    def resolved_openrouter_drafting_model(self) -> str:
        return self.openrouter_drafting_model.strip() or self.openrouter_model

    @property
    def resolved_openrouter_classification_model(self) -> str:
        return self.openrouter_classification_model.strip() or self.openrouter_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
