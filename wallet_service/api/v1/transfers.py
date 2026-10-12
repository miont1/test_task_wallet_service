import hashlib
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.core.errors import (
    AppError,
    ConflictError,
    InsufficientFundsError,
    NotFoundError,
)
from wallet_service.db.models import (
    Account,
    IdempotencyRecord,
    Transaction,
    TransactionType,
)
from wallet_service.db.session import get_db_session
from wallet_service.dependencies import get_current_account
from wallet_service.schemas.transfer import TransferCreateRequest, TransferResponse

router = APIRouter(prefix="/v1/transfers", tags=["Transfers"])


@router.post(
    "",
    response_model=TransferResponse,
    status_code=status.HTTP_200_OK,
    summary="Transfer USD funds between accounts with strict idempotency",
)
async def transfer_funds(
    request: Request,
    sender: Annotated[Account, Depends(get_current_account)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> TransferResponse | Response:
    """Executes an internal USD balance transfer with strict idempotency and deadlock prevention.

    Guarantees:
    - Same Idempotency-Key + same body -> returns cached response without duplicate execution.
    - Same Idempotency-Key + different body -> 409 Conflict.
    - Deterministic account row locking ordered by account.id to prevent deadlocks.
    - Sender balance never drops below zero.
    - Ledger records created for both sender (transfer_out) and recipient (transfer_in).
    """
    raw_body = await request.body()
    current_hash = hashlib.sha256(raw_body).hexdigest()

    # 1. Idempotency check
    existing_record = await session.get(IdempotencyRecord, idempotency_key)
    if existing_record is not None:
        if (
            existing_record.account_id != sender.id
            or existing_record.request_hash != current_hash
        ):
            raise ConflictError(
                message="Idempotency key was previously used with a different request payload or account",
                code="idempotency_conflict",
            )
        return Response(
            content=existing_record.response_body,
            status_code=existing_record.response_status_code,
            media_type="application/json",
        )

    # 2. Parse payload
    try:
        payload = TransferCreateRequest.model_validate_json(raw_body)
    except ValidationError as exc:
        raise AppError(
            message="Invalid transfer request payload",
            code="validation_error",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={"errors": exc.errors()},
        ) from exc

    # 3. Validation: self-transfer disallowed
    if sender.id == payload.to_account_id:
        raise AppError(
            message="Cannot transfer funds to your own account",
            code="self_transfer_not_allowed",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # 4. Deadlock-free row-level locking (order accounts by ID ascending)
    lock_ids = sorted([sender.id, payload.to_account_id])
    accounts_by_id: dict[str, Account] = {}
    for acc_id in lock_ids:
        stmt = select(Account).where(Account.id == acc_id).with_for_update()
        acc = await session.scalar(stmt)
        if acc is not None:
            accounts_by_id[acc.id] = acc

    recipient = accounts_by_id.get(payload.to_account_id)
    if recipient is None:
        raise NotFoundError(
            message=f"Recipient account '{payload.to_account_id}' not found",
            code="recipient_not_found",
        )

    # Re-reference sender from the locked row
    sender = accounts_by_id[sender.id]

    # 5. Check sender balance
    if sender.balance_usd < payload.amount:
        raise InsufficientFundsError(
            message=f"Insufficient balance: available {sender.balance_usd} USD, required {payload.amount} USD",
            details={
                "available_balance": str(sender.balance_usd),
                "transfer_amount": str(payload.amount),
            },
        )

    # 6. Apply balances
    transfer_id = f"trf_{uuid4().hex[:16]}"
    sender.balance_usd -= payload.amount
    recipient.balance_usd += payload.amount

    # 7. Record transactions
    txn_out = Transaction(
        account_id=sender.id,
        type=TransactionType.TRANSFER_OUT.value,
        amount_usd=payload.amount,
        amount_credits=0,
        balance_usd_after=sender.balance_usd,
        balance_credits_after=sender.balance_credits,
        description=f"Transfer to {recipient.id}",
        reference_id=transfer_id,
    )
    txn_in = Transaction(
        account_id=recipient.id,
        type=TransactionType.TRANSFER_IN.value,
        amount_usd=payload.amount,
        amount_credits=0,
        balance_usd_after=recipient.balance_usd,
        balance_credits_after=recipient.balance_credits,
        description=f"Transfer from {sender.id}",
        reference_id=transfer_id,
    )
    session.add_all([txn_out, txn_in])

    # 8. Build response
    now_iso = datetime.now(UTC).isoformat()
    resp_obj = TransferResponse(
        transfer_id=transfer_id,
        from_account_id=sender.id,
        to_account_id=recipient.id,
        amount=payload.amount,
        from_balance_usd_after=sender.balance_usd,
        created_at=now_iso,
    )
    resp_body = resp_obj.model_dump_json()

    # 9. Store idempotency record
    idempotency_entry = IdempotencyRecord(
        idempotency_key=idempotency_key,
        account_id=sender.id,
        request_hash=current_hash,
        response_status_code=status.HTTP_200_OK,
        response_body=resp_body,
    )
    session.add(idempotency_entry)
    await session.commit()

    return resp_obj
