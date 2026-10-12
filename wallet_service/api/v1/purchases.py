from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.core.errors import InsufficientFundsError, NotFoundError
from wallet_service.db.models import Account, Transaction, TransactionType
from wallet_service.db.session import get_db_session
from wallet_service.dependencies import get_current_account
from wallet_service.schemas.purchase import PurchaseCreateRequest, PurchaseResponse
from wallet_service.services.money import calculate_credits_cost

router = APIRouter(prefix="/v1/purchases", tags=["Purchases"])


@router.post(
    "",
    response_model=PurchaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Purchase credit packages with USD balance applying volume discounts",
)
async def purchase_credits(
    payload: PurchaseCreateRequest,
    current_account: Annotated[Account, Depends(get_current_account)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PurchaseResponse:
    """Purchases service credits using the user's USD ledger balance.

    Pricing rules:
    - Base price: 0.10 USD per credit
    - 500+ credits: 5% discount
    - 1000+ credits: 12.5% discount
    - Final price rounded to cents with ROUND_HALF_UP

    Atomically locks the account row, checks balance, updates balances and logs a ledger transaction.
    """
    cost_usd = calculate_credits_cost(payload.credits)

    # 1. Lock account row to prevent race conditions
    stmt = select(Account).where(Account.id == current_account.id).with_for_update()
    account = await session.scalar(stmt)
    if account is None:
        raise NotFoundError(
            message="Account not found",
            code="account_not_found",
        )

    # 2. Check sufficient USD balance
    if account.balance_usd < cost_usd:
        raise InsufficientFundsError(
            message=f"Insufficient USD balance to purchase {payload.credits} credits",
            details={
                "required_usd": str(cost_usd),
                "available_usd": str(account.balance_usd),
            },
        )

    # 3. Deduct USD and credit internal credits
    purchase_id = f"pur_{uuid4().hex[:16]}"
    account.balance_usd -= cost_usd
    account.balance_credits += payload.credits

    # 4. Record ledger transaction
    txn = Transaction(
        account_id=account.id,
        type=TransactionType.PURCHASE.value,
        amount_usd=cost_usd,
        amount_credits=payload.credits,
        balance_usd_after=account.balance_usd,
        balance_credits_after=account.balance_credits,
        description=f"Purchased {payload.credits} credits for {cost_usd} USD",
        reference_id=purchase_id,
    )
    session.add(txn)
    await session.commit()

    return PurchaseResponse(
        purchase_id=purchase_id,
        account_id=account.id,
        credits_purchased=payload.credits,
        cost_usd=cost_usd,
        balance_usd_after=account.balance_usd,
        balance_credits_after=account.balance_credits,
        created_at=datetime.now(UTC).isoformat(),
    )
