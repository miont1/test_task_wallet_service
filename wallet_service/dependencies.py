from typing import Annotated

import httpx
from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.config import Settings, get_settings
from wallet_service.core.errors import UnauthorizedError
from wallet_service.core.security import hash_api_key
from wallet_service.db.models import Account
from wallet_service.db.session import get_db_session
from wallet_service.services.provider_client import ProviderClient

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Retrieves shared httpx.AsyncClient from FastAPI application state."""
    client: httpx.AsyncClient | None = getattr(request.app.state, "http_client", None)
    if client is None:
        raise RuntimeError(
            "Application HTTP client has not been initialized in app.state"
        )
    return client


def get_provider_client(
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProviderClient:
    """Dependency returning configured ProviderClient."""
    return ProviderClient(client=client, settings=settings)


async def get_current_account(
    api_key: Annotated[str | None, Security(api_key_header)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Account:
    """Authenticates the incoming request using the X-API-Key header."""
    if not api_key:
        raise UnauthorizedError(
            message="Missing X-API-Key header",
            code="missing_api_key",
        )

    key_hash = hash_api_key(api_key)
    stmt = select(Account).where(Account.api_key_hash == key_hash)
    account = await session.scalar(stmt)

    if account is None:
        raise UnauthorizedError(
            message="Invalid API key",
            code="invalid_api_key",
        )

    return account
