from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_key: str = Field(
        default="mock-provider-key-123",
        description="Bearer token required for provider API access",
        alias="PROVIDER_API_KEY",
    )
    webhook_secret: str = Field(
        default="mock-webhook-secret-456",
        description="HMAC secret used to sign outgoing webhooks",
        alias="PROVIDER_WEBHOOK_SECRET",
    )
    base_pay_url: str = Field(
        default="https://mock-provider.local/pay",
        description="Base URL for generated invoice payment links",
        alias="PROVIDER_BASE_PAY_URL",
    )
    host: str = Field(default="0.0.0.0", alias="PROVIDER_HOST")
    port: int = Field(default=8001, alias="PROVIDER_PORT")
    webhook_timeout_seconds: float = Field(
        default=5.0, alias="PROVIDER_WEBHOOK_TIMEOUT"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
