from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.config import Settings, get_settings
from wallet_service.core.errors import AppError, NotFoundError
from wallet_service.db.models import (
    FINAL_DEPOSIT_STATUSES,
    Account,
    Deposit,
    DepositStatus,
    ProcessedWebhook,
    Transaction,
    TransactionType,
)
from wallet_service.db.session import get_db_session
from wallet_service.schemas.webhook import ProviderWebhookPayload
from wallet_service.services.money import calculate_credited_amount
from wallet_service.services.webhook_validator import verify_webhook_signature

router = APIRouter(prefix="/v1/webhooks", tags=["Webhooks"])


@router.post(
    "/provider",
    status_code=status.HTTP_200_OK,
    summary="Receive and process asynchronous payment provider webhooks",
)
async def receive_provider_webhook(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_signature: Annotated[str | None, Header(alias="X-Signature")] = None,
    x_timestamp: Annotated[str | None, Header(alias="X-Timestamp")] = None,
) -> dict[str, str]:
    """Processes signed provider webhooks with idempotency and replay protection.

    - Verifies HMAC-SHA256 signature and timestamp freshness (5 min tolerance).
    - Prevents double crediting on duplicate event_id.
    - Credits net amount (paid - 1.5% fee) for paid and partially_paid statuses.
    - Closes deposit without crediting for expired status.
    - Ignores webhooks arriving after deposit has already been closed.
    """
    raw_body = await request.body()

    # 1. Verify signature and timestamp freshness (raises 401 if invalid)
    verify_webhook_signature(
        secret=settings.provider_webhook_secret,
        timestamp_header=x_timestamp,
        signature_header=x_signature,
        raw_body_bytes=raw_body,
        tolerance_seconds=settings.webhook_timestamp_tolerance_seconds,
    )

    # 2. Parse JSON payload
    try:
        payload = ProviderWebhookPayload.model_validate_json(raw_body)
    except ValidationError as exc:
        raise AppError(
            message="Invalid webhook payload format",
            code="invalid_webhook_payload",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"errors": exc.errors()},
        ) from exc

    # 3. Deduplicate by event_id: identical event_id must never credit money twice
    existing_event = await session.get(ProcessedWebhook, payload.event_id)
    if existing_event is not None:
        return {"status": "ok", "message": "Duplicate event already processed"}

    # 4. Find deposit by invoice_id with row lock
    stmt = select(Deposit).where(Deposit.invoice_id == payload.invoice_id).with_for_update()
    deposit = await session.scalar(stmt)
    if deposit is None:
        raise NotFoundError(
            message=f"No deposit found for invoice '{payload.invoice_id}'",
            code="deposit_not_found",
        )

    # 5. Check if deposit is already closed (final status)
    if deposit.status in FINAL_DEPOSIT_STATUSES:
        # Record webhook event to avoid re-processing, but do NOT credit or modify state
        processed = ProcessedWebhook(
            event_id=payload.event_id,
            invoice_id=payload.invoice_id,
            status=payload.status,
            paid_amount=payload.paid_amount,
        )
        session.add(processed)
        await session.commit()
        return {"status": "ok", "message": "Deposit is already closed; state unchanged"}

    # 6. Process pending deposit based on webhook status
    if payload.status in (DepositStatus.PAID.value, DepositStatus.PARTIALLY_PAID.value):
        fee, credited = calculate_credited_amount(payload.paid_amount)
        deposit.status = payload.status
        deposit.fee = fee
        deposit.credited_amount = credited

        # Credit account balance with row lock
        acc_stmt = select(Account).where(Account.id == deposit.account_id).with_for_update()
        account = await session.scalar(acc_stmt)
        if account is None:
            raise NotFoundError(message="Associated account not found", code="account_not_found")

        account.balance_usd += credited

        # Record ledger transaction
        txn = Transaction(
            account_id=account.id,
            type=TransactionType.DEPOSIT.value,
            amount_usd=credited,
            amount_credits=0,
            balance_usd_after=account.balance_usd,
            balance_credits_after=account.balance_credits,
            description=f"Deposit credited: paid {payload.paid_amount} USD, fee {fee} USD",
            reference_id=deposit.id,
        )
        session.add(txn)

    elif payload.status == DepositStatus.EXPIRED.value:
        deposit.status = DepositStatus.EXPIRED.value
        deposit.fee = Decimal("0.00")
        deposit.credited_amount = Decimal("0.00")

    # Record event_id to ensure idempotency
    processed_event = ProcessedWebhook(
        event_id=payload.event_id,
        invoice_id=payload.invoice_id,
        status=payload.status,
        paid_amount=payload.paid_amount,
    )
    session.add(processed_event)
    await session.commit()

    return {"status": "ok", "message": f"Deposit updated to {deposit.status}"}
