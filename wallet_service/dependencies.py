from typing import Annotated

from fastapi import Depends, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.core.errors import UnauthorizedError
from wallet_service.core.security import hash_api_key
from wallet_service.db.models import Account
from wallet_service.db.session import get_db_session

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


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
