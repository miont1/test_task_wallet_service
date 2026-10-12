from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.core.security import generate_api_key, hash_api_key
from wallet_service.db.models import Account
from wallet_service.db.session import get_db_session
from wallet_service.dependencies import get_current_account
from wallet_service.schemas.account import AccountCreateResponse, AccountMeResponse

router = APIRouter(prefix="/v1/accounts", tags=["Accounts"])


@router.post(
    "",
    response_model=AccountCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user account and generate an API key",
)
async def create_account(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AccountCreateResponse:
    """Creates a new user account.

    Generates a secure API key. The raw API key is returned ONLY once in this response.
    """
    raw_api_key = generate_api_key()
    api_key_hash = hash_api_key(raw_api_key)

    account = Account(
        api_key_hash=api_key_hash,
        balance_usd=Decimal("0.00"),
        balance_credits=0,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)

    return AccountCreateResponse(
        account_id=account.id,
        api_key=raw_api_key,
        balance_usd=account.balance_usd,
        balance_credits=account.balance_credits,
    )


@router.get(
    "/me",
    response_model=AccountMeResponse,
    summary="Get current user balances in USD and credits",
)
async def get_my_account(
    current_account: Annotated[Account, Depends(get_current_account)],
) -> AccountMeResponse:
    """Returns balance in USD and credits for the authenticated user."""
    return AccountMeResponse(
        account_id=current_account.id,
        balance_usd=current_account.balance_usd,
        balance_credits=current_account.balance_credits,
    )
