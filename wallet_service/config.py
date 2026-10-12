from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(
        default="postgresql+asyncpg://ledger_user:ledger_pass@localhost:5432/wallet_db",
        description="Async database connection string (PostgreSQL or SQLite)",
        alias="DATABASE_URL",
    )
    provider_base_url: str = Field(
        default="http://localhost:8001",
        description="Base URL for provider-mock service",
        alias="PROVIDER_BASE_URL",
    )
    provider_api_key: str = Field(
        default="mock-provider-key-123",
        description="Bearer token for provider-mock API calls",
        alias="PROVIDER_API_KEY",
    )
    provider_webhook_secret: str = Field(
        default="mock-webhook-secret-456",
        description="Shared secret for verifying HMAC-SHA256 provider webhooks",
        alias="PROVIDER_WEBHOOK_SECRET",
    )
    webhook_timestamp_tolerance_seconds: int = Field(
        default=300,
        description="Maximum allowed timestamp drift for incoming webhooks (5 minutes)",
        alias="WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS",
    )
    provider_timeout_seconds: float = Field(
        default=5.0,
        description="Timeout for outbound HTTP requests to payment provider",
        alias="PROVIDER_TIMEOUT_SECONDS",
    )
    callback_url: str = Field(
        default="http://localhost:8000/v1/webhooks/provider",
        description="Default callback URL registered when creating provider invoices",
        alias="WALLET_CALLBACK_URL",
    )
    host: str = Field(default="0.0.0.0", alias="WALLET_HOST")
    port: int = Field(default=8000, alias="WALLET_PORT")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
