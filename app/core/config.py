from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Miller Schackman API"
    app_version: str = "0.1.0"
    environment: str = Field(default="local")
    debug: bool = False
    log_level: str = "INFO"
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

    rabbitmq_url: str = "amqp://guest:guest@localhost:55672/"
    crm_sync_exchange_name: str = "miller_schackman.events"
    crm_sync_queue_name: str = "miller_schackman.crm_sync"
    crm_sync_worker_prefetch_count: int = 1
    crm_sync_incremental_interval_seconds: int = 300
    crm_sync_scheduler_poll_seconds: int = 60
    crm_sync_scheduler_workspace_limit: int = 100
    temporal_address: str = "localhost:57233"
    temporal_task_queue: str = "miller-schackman-task-queue"

    crm_provider: str = "follow_up_boss"
    fub_api_key: SecretStr | None = None
    fub_base_url: str = "https://api.followupboss.com/v1"

    llm_provider: str = "openrouter"
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_allowed_models: list[str] = ["openai/gpt-4o-mini"]

    # Valid values: "twilio" or "sink" (dev-only, no external calls).
    sms_provider: str = "twilio"
    twilio_account_sid: SecretStr | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_from_phone: str = ""

    # Valid values: "sendgrid", "mailpit" (dev SMTP inbox), or "sink".
    email_provider: str = "sendgrid"
    sendgrid_api_key: SecretStr | None = None
    sendgrid_event_webhook_public_key: SecretStr | None = None
    sendgrid_from_email: str = ""
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
    listing_context_enrichment_cache_ttl_minutes: int = 360
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

    @field_validator("openrouter_allowed_models")
    @classmethod
    def openrouter_allowed_models_must_be_non_empty(cls, value: list[str]) -> list[str]:
        normalized = tuple(dict.fromkeys(item.strip() for item in value if item.strip()))
        if not normalized:
            raise ValueError("openrouter_allowed_models must contain at least one model")
        return list(normalized)

    @model_validator(mode="after")
    def openrouter_model_must_be_allowed(self) -> "Settings":
        if self.openrouter_model not in self.openrouter_allowed_models:
            raise ValueError("openrouter_model must be included in openrouter_allowed_models")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
