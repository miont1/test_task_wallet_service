from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.db.models import Account, Transaction
from wallet_service.db.session import get_db_session
from wallet_service.dependencies import get_current_account
from wallet_service.schemas.transaction import (
    TransactionItem,
    TransactionListResponse,
)
from wallet_service.services.pagination import decode_cursor, encode_cursor

router = APIRouter(prefix="/v1/transactions", tags=["Transactions"])


@router.get(
    "",
    response_model=TransactionListResponse,
    status_code=status.HTTP_200_OK,
    summary="Get paginated transaction history for the authenticated user",
)
async def list_transactions(
    current_account: Annotated[Account, Depends(get_current_account)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[
        int, Query(ge=1, le=100, description="Max number of transactions to return")
    ] = 20,
    cursor: Annotated[
        str | None, Query(description="Keyset pagination cursor from previous response")
    ] = None,
) -> TransactionListResponse:
    """Returns chronologically ordered (newest first) transactions for the current user.

    Uses cursor-based (keyset) pagination on (created_at DESC, id DESC) to guarantee:
    - O(1) database index seek time.
    - Consistency under continuous writes (no page drift or duplicated entries).
    """
    stmt = select(Transaction).where(Transaction.account_id == current_account.id)

    if cursor is not None:
        cursor_time, cursor_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Transaction.created_at < cursor_time,
                and_(Transaction.created_at == cursor_time, Transaction.id < cursor_id),
            )
        )

    # Order newest first, tie-break by ID descending, fetch limit + 1 to check has_more
    stmt = stmt.order_by(Transaction.created_at.desc(), Transaction.id.desc()).limit(
        limit + 1
    )
    results = await session.scalars(stmt)
    records = list(results.all())

    has_more = len(records) > limit
    page_records = records[:limit]
    next_cursor = None
    if has_more and page_records:
        last_rec = page_records[-1]
        next_cursor = encode_cursor(last_rec.created_at, last_rec.id)

    items = [
        TransactionItem(
            id=rec.id,
            type=rec.type,
            amount_usd=rec.amount_usd,
            amount_credits=rec.amount_credits,
            balance_usd_after=rec.balance_usd_after,
            balance_credits_after=rec.balance_credits_after,
            description=rec.description,
            reference_id=rec.reference_id,
            created_at=rec.created_at.isoformat(),
        )
        for rec in page_records
    ]

    return TransactionListResponse(
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
    )
