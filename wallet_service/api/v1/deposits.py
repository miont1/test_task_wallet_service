from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.db.models import Account, Deposit, DepositStatus
from wallet_service.db.session import get_db_session
from wallet_service.dependencies import get_current_account, get_provider_client
from wallet_service.schemas.deposit import DepositCreateRequest, DepositCreateResponse
from wallet_service.services.provider_client import ProviderClient

router = APIRouter(prefix="/v1/deposits", tags=["Deposits"])


@router.post(
    "",
    response_model=DepositCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new deposit and generate provider payment link",
)
async def create_deposit(
    payload: DepositCreateRequest,
    current_account: Annotated[Account, Depends(get_current_account)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    provider_client: Annotated[ProviderClient, Depends(get_provider_client)],
) -> DepositCreateResponse:
    """Creates a new deposit in pending status, calls provider to generate invoice and returns payment link."""
    deposit_id = f"dep_{uuid4().hex[:16]}"

    # Call external payment provider to generate invoice
    invoice = await provider_client.create_invoice(
        amount=payload.amount,
        external_id=deposit_id,
    )

    deposit = Deposit(
        id=deposit_id,
        account_id=current_account.id,
        invoice_id=invoice.invoice_id,
        amount=payload.amount,
        status=DepositStatus.PENDING.value,
        pay_url=invoice.pay_url,
    )
    session.add(deposit)
    await session.commit()
    await session.refresh(deposit)

    return DepositCreateResponse(
        deposit_id=deposit.id,
        status=deposit.status,
        amount=deposit.amount,
        pay_url=invoice.pay_url,
    )
