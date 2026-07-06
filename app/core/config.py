from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Miller Schackman API"
    app_version: str = "0.1.0"
    environment: str = Field(default="local")
    debug: bool = False
    log_level: str = "INFO"

    api_v1_prefix: str = "/api/v1"
    allowed_origins: list[str] = ["http://localhost:5173"]

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/miller_schackman"
    database_migration_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/miller_schackman"
    )

    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    temporal_address: str = "localhost:7233"

    # CRM provider
    crm_provider: str = "follow_up_boss"
    fub_api_key: SecretStr | None = None
    fub_base_url: str = "https://api.followupboss.com/v1"

    # LLM provider
    llm_provider: str = "openrouter"
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-4o-mini"

    # SMS provider
    sms_provider: str = "twilio"
    twilio_account_sid: SecretStr | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_from_phone: str = ""

    # Email provider
    email_provider: str = "sendgrid"
    sendgrid_api_key: SecretStr | None = None
    sendgrid_from_email: str = ""

    # File storage provider
    storage_provider: str = "s3"
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    s3_bucket: str = ""
    s3_region: str = "us-east-1"

    # Cache provider
    cache_provider: str = "redis"
    redis_url: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
