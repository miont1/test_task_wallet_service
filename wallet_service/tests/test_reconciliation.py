from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.db.models import (
    Account,
    Deposit,
    DepositStatus,
    ProcessedWebhook,
    Transaction,
)
from wallet_service.dependencies import get_provider_client
from wallet_service.main import app
from wallet_service.services.provider_client import (
    ProviderInvoiceDetail,
    ProviderUnavailableError,
)
from wallet_service.services.reconciliation_service import run_reconciliation


@pytest.mark.asyncio
async def test_reconciliation_recovers_paid_invoice(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    # 1. Create account
    account = Account(
        api_key_hash="hash_rec_1",
        balance_usd=Decimal("0.00"),
        balance_credits=0,
    )
    db_session.add(account)
    await db_session.flush()

    # 2. Create pending deposit older than 10 minutes
    old_time = datetime.now(UTC) - timedelta(minutes=10)
    deposit = Deposit(
        account_id=account.id,
        amount=Decimal("100.00"),
        status=DepositStatus.PENDING.value,
        invoice_id="inv_rec_100",
        pay_url="https://pay.example/inv_rec_100",
        created_at=old_time,
    )
    db_session.add(deposit)
    await db_session.commit()

    # 3. Mock ProviderClient returning paid status
    class MockProviderClient:
        async def get_invoice(self, invoice_id: str) -> ProviderInvoiceDetail:
            return ProviderInvoiceDetail(
                invoice_id=invoice_id,
                status="paid",
                amount=Decimal("100.00"),
                paid_amount=Decimal("100.00"),
                currency="USD",
            )

    app.dependency_overrides[get_provider_client] = lambda: MockProviderClient()

    try:
        # 4. Trigger reconciliation via API
        response = await client.post(
            "/v1/reconciliation/run",
            params={"older_than_minutes": 5},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["scanned_count"] == 1
        assert data["reconciled_count"] == 1
        detail = data["details"][0]
        assert detail["deposit_id"] == deposit.id
        assert detail["old_status"] == DepositStatus.PENDING.value
        assert detail["new_status"] == DepositStatus.PAID.value
        assert detail["credited_amount"] == "98.50"

        # 5. Verify database updates
        refreshed_acc = await db_session.scalar(
            select(Account).where(Account.id == account.id)
        )
        assert refreshed_acc is not None
        assert refreshed_acc.balance_usd == Decimal("98.50")

        refreshed_dep = await db_session.scalar(
            select(Deposit).where(Deposit.id == deposit.id)
        )
        assert refreshed_dep is not None
        assert refreshed_dep.status == DepositStatus.PAID.value
        assert refreshed_dep.fee == Decimal("1.50")
        assert refreshed_dep.credited_amount == Decimal("98.50")

        # 6. Verify ProcessedWebhook idempotency lock added
        pw = await db_session.scalar(
            select(ProcessedWebhook).where(ProcessedWebhook.invoice_id == "inv_rec_100")
        )
        assert pw is not None
        assert pw.event_id == "rec_inv_rec_100"

        # 7. Verify Transaction record exists
        txn = await db_session.scalar(
            select(Transaction).where(Transaction.reference_id == deposit.id)
        )
        assert txn is not None
        assert txn.amount_usd == Decimal("98.50")
    finally:
        app.dependency_overrides.pop(get_provider_client, None)


@pytest.mark.asyncio
async def test_reconciliation_marks_expired_invoice(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    account = Account(
        api_key_hash="hash_rec_2",
        balance_usd=Decimal("50.00"),
        balance_credits=0,
    )
    db_session.add(account)
    await db_session.flush()

    old_time = datetime.now(UTC) - timedelta(minutes=15)
    deposit = Deposit(
        account_id=account.id,
        amount=Decimal("20.00"),
        status=DepositStatus.PENDING.value,
        invoice_id="inv_rec_exp",
        created_at=old_time,
    )
    db_session.add(deposit)
    await db_session.commit()

    class MockProviderClient:
        async def get_invoice(self, invoice_id: str) -> ProviderInvoiceDetail:
            return ProviderInvoiceDetail(
                invoice_id=invoice_id,
                status="expired",
                amount=Decimal("20.00"),
                paid_amount=Decimal("0.00"),
                currency="USD",
            )

    app.dependency_overrides[get_provider_client] = lambda: MockProviderClient()

    try:
        response = await client.post(
            "/v1/reconciliation/run",
            params={"older_than_minutes": 5},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["scanned_count"] == 1
        assert data["reconciled_count"] == 1
        assert data["details"][0]["new_status"] == DepositStatus.EXPIRED.value
        assert data["details"][0]["credited_amount"] == "0.00"

        refreshed_acc = await db_session.scalar(
            select(Account).where(Account.id == account.id)
        )
        assert refreshed_acc is not None
        assert refreshed_acc.balance_usd == Decimal("50.00")  # untouched

        refreshed_dep = await db_session.scalar(
            select(Deposit).where(Deposit.id == deposit.id)
        )
        assert refreshed_dep is not None
        assert refreshed_dep.status == DepositStatus.EXPIRED.value
    finally:
        app.dependency_overrides.pop(get_provider_client, None)


@pytest.mark.asyncio
async def test_reconciliation_skips_recent_deposits(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    account = Account(
        api_key_hash="hash_rec_3",
        balance_usd=Decimal("0.00"),
        balance_credits=0,
    )
    db_session.add(account)
    await db_session.flush()

    # Deposit created 1 minute ago
    recent_time = datetime.now(UTC) - timedelta(minutes=1)
    deposit = Deposit(
        account_id=account.id,
        amount=Decimal("15.00"),
        status=DepositStatus.PENDING.value,
        invoice_id="inv_rec_recent",
        created_at=recent_time,
    )
    db_session.add(deposit)
    await db_session.commit()

    class MockProviderClient:
        async def get_invoice(self, invoice_id: str) -> ProviderInvoiceDetail:
            return ProviderInvoiceDetail(
                invoice_id=invoice_id,
                status="paid",
                amount=Decimal("15.00"),
                paid_amount=Decimal("15.00"),
                currency="USD",
            )

    app.dependency_overrides[get_provider_client] = lambda: MockProviderClient()

    try:
        # Require >= 5 minutes
        response = await client.post(
            "/v1/reconciliation/run",
            params={"older_than_minutes": 5},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["scanned_count"] == 0
        assert data["reconciled_count"] == 0
    finally:
        app.dependency_overrides.pop(get_provider_client, None)


@pytest.mark.asyncio
async def test_reconciliation_handles_provider_outage(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    account = Account(
        api_key_hash="hash_rec_4",
        balance_usd=Decimal("0.00"),
        balance_credits=0,
    )
    db_session.add(account)
    await db_session.flush()

    old_time = datetime.now(UTC) - timedelta(minutes=10)
    deposit = Deposit(
        account_id=account.id,
        amount=Decimal("10.00"),
        status=DepositStatus.PENDING.value,
        invoice_id="inv_rec_err",
        created_at=old_time,
    )
    db_session.add(deposit)
    await db_session.commit()

    class MockProviderClient:
        async def get_invoice(self, invoice_id: str) -> ProviderInvoiceDetail:
            raise ProviderUnavailableError("Provider server down")

    app.dependency_overrides[get_provider_client] = lambda: MockProviderClient()

    try:
        response = await client.post(
            "/v1/reconciliation/run",
            params={"older_than_minutes": 5},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["scanned_count"] == 1
        assert data["reconciled_count"] == 0

        # Deposit remains pending
        refreshed_dep = await db_session.scalar(
            select(Deposit).where(Deposit.id == deposit.id)
        )
        assert refreshed_dep is not None
        assert refreshed_dep.status == DepositStatus.PENDING.value
    finally:
        app.dependency_overrides.pop(get_provider_client, None)


@pytest.mark.asyncio
async def test_run_reconciliation_direct_service_call(
    db_session: AsyncSession,
) -> None:
    account = Account(
        api_key_hash="hash_rec_5",
        balance_usd=Decimal("0.00"),
        balance_credits=0,
    )
    db_session.add(account)
    await db_session.flush()

    old_time = datetime.now(UTC) - timedelta(minutes=10)
    deposit = Deposit(
        account_id=account.id,
        amount=Decimal("50.00"),
        status=DepositStatus.PENDING.value,
        invoice_id="inv_rec_direct",
        created_at=old_time,
    )
    db_session.add(deposit)
    await db_session.commit()

    class MockProviderClient:
        async def get_invoice(self, invoice_id: str) -> ProviderInvoiceDetail:
            return ProviderInvoiceDetail(
                invoice_id=invoice_id,
                status="paid",
                amount=Decimal("50.00"),
                paid_amount=Decimal("50.00"),
                currency="USD",
            )

    result = await run_reconciliation(
        session=db_session,
        provider_client=MockProviderClient(),  # type: ignore[arg-type]
        older_than_minutes=5,
    )

    assert result.scanned_count == 1
    assert result.reconciled_count == 1
    assert result.details[0].new_status == "paid"
