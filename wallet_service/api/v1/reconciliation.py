from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.db.session import get_db_session
from wallet_service.dependencies import get_provider_client
from wallet_service.schemas.reconciliation import ReconciliationResponse
from wallet_service.services.provider_client import ProviderClient
from wallet_service.services.reconciliation_service import run_reconciliation

router = APIRouter(prefix="/v1/reconciliation", tags=["Reconciliation"])


@router.post(
    "/run",
    response_model=ReconciliationResponse,
    status_code=status.HTTP_200_OK,
    summary="Reconcile pending deposits older than threshold against payment provider",
)
async def trigger_reconciliation(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    provider_client: Annotated[ProviderClient, Depends(get_provider_client)],
    older_than_minutes: Annotated[
        int,
        Query(ge=0, description="Age in minutes for pending deposits to reconcile"),
    ] = 5,
) -> ReconciliationResponse:
    """Finds deposits stuck in pending status older than N minutes.

    Queries the payment provider via GET /invoices/{id} to recover lost webhooks and credit accounts.
    """
    return await run_reconciliation(
        session=session,
        provider_client=provider_client,
        older_than_minutes=older_than_minutes,
    )
