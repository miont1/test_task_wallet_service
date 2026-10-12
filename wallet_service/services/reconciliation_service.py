import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.core.errors import AppError
from wallet_service.db.models import (
    FINAL_DEPOSIT_STATUSES,
    Account,
    Deposit,
    DepositStatus,
    ProcessedWebhook,
    Transaction,
    TransactionType,
)
from wallet_service.schemas.reconciliation import (
    ReconciledDepositItem,
    ReconciliationResponse,
)
from wallet_service.services.money import calculate_credited_amount
from wallet_service.services.provider_client import ProviderClient

logger = logging.getLogger(__name__)


async def run_reconciliation(
    session: AsyncSession,
    provider_client: ProviderClient,
    older_than_minutes: int = 5,
) -> ReconciliationResponse:
    """Scans pending deposits older than N minutes, checks provider state, and updates them."""
    cutoff_time = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
    stmt = (
        select(Deposit)
        .where(
            Deposit.status == DepositStatus.PENDING.value,
            Deposit.created_at <= cutoff_time,
            Deposit.invoice_id.is_not(None),
        )
        .order_by(Deposit.created_at.asc())
    )
    pending_deposits = (await session.scalars(stmt)).all()
    reconciled_items: list[ReconciledDepositItem] = []

    for dep in pending_deposits:
        if not dep.invoice_id:
            continue

        try:
            invoice = await provider_client.get_invoice(dep.invoice_id)
        except (AppError, httpx.HTTPError) as exc:
            logger.warning(
                "Failed to query invoice %s during reconciliation: %s",
                dep.invoice_id,
                exc,
            )
            continue

        if invoice.status == DepositStatus.PENDING.value:
            continue

        # Lock deposit row and re-verify status to prevent race condition
        locked_dep = await session.scalar(
            select(Deposit).where(Deposit.id == dep.id).with_for_update()
        )
        if locked_dep is None or locked_dep.status in FINAL_DEPOSIT_STATUSES:
            continue

        old_status = locked_dep.status
        credited = Decimal("0.00")

        if invoice.status in (
            DepositStatus.PAID.value,
            DepositStatus.PARTIALLY_PAID.value,
        ):
            fee, credited = calculate_credited_amount(invoice.paid_amount)
            locked_dep.status = invoice.status
            locked_dep.fee = fee
            locked_dep.credited_amount = credited

            acc = await session.scalar(
                select(Account)
                .where(Account.id == locked_dep.account_id)
                .with_for_update()
            )
            if acc is not None:
                acc.balance_usd += credited
                txn = Transaction(
                    account_id=acc.id,
                    type=TransactionType.DEPOSIT.value,
                    amount_usd=credited,
                    amount_credits=0,
                    balance_usd_after=acc.balance_usd,
                    balance_credits_after=acc.balance_credits,
                    description=f"Reconciled deposit: paid {invoice.paid_amount} USD, fee {fee} USD",
                    reference_id=locked_dep.id,
                )
                session.add(txn)

            # Guard against late-arriving webhooks by saving duplicate lock
            processed_event = ProcessedWebhook(
                event_id=f"rec_{locked_dep.invoice_id}",
                invoice_id=locked_dep.invoice_id,
                status=invoice.status,
                paid_amount=invoice.paid_amount,
            )
            session.add(processed_event)

        elif invoice.status == DepositStatus.EXPIRED.value:
            locked_dep.status = DepositStatus.EXPIRED.value
            locked_dep.fee = Decimal("0.00")
            locked_dep.credited_amount = Decimal("0.00")

        await session.commit()

        reconciled_items.append(
            ReconciledDepositItem(
                deposit_id=locked_dep.id,
                invoice_id=locked_dep.invoice_id,
                account_id=locked_dep.account_id,
                old_status=old_status,
                new_status=locked_dep.status,
                credited_amount=credited,
            )
        )

    return ReconciliationResponse(
        scanned_count=len(pending_deposits),
        reconciled_count=len(reconciled_items),
        details=reconciled_items,
    )
