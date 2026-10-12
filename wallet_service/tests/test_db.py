from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.db.models import (
    Account,
    Deposit,
    DepositStatus,
    IdempotencyRecord,
    ProcessedWebhook,
    Transaction,
    TransactionType,
)


@pytest.mark.asyncio
async def test_account_creation_and_defaults(db_session: AsyncSession) -> None:
    account = Account(
        api_key_hash="hash_test_12345",
        balance_usd=Decimal("100.00"),
        balance_credits=50,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    assert account.id.startswith("acc_")
    assert account.balance_usd == Decimal("100.00")
    assert account.balance_credits == 50
    assert account.created_at is not None
    assert account.updated_at is not None


@pytest.mark.asyncio
async def test_account_api_key_hash_uniqueness(db_session: AsyncSession) -> None:
    acc1 = Account(api_key_hash="duplicate_hash")
    acc2 = Account(api_key_hash="duplicate_hash")
    db_session.add_all([acc1, acc2])

    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_deposit_creation_and_relationship(db_session: AsyncSession) -> None:
    account = Account(api_key_hash="hash_dep_user")
    db_session.add(account)
    await db_session.commit()

    deposit = Deposit(
        account_id=account.id,
        invoice_id="inv_mock_123",
        amount=Decimal("25.00"),
        status=DepositStatus.PENDING.value,
        pay_url="http://mock-provider.local/pay/inv_mock_123",
    )
    db_session.add(deposit)
    await db_session.commit()
    await db_session.refresh(deposit)

    assert deposit.id.startswith("dep_")
    assert deposit.status == DepositStatus.PENDING.value
    assert deposit.amount == Decimal("25.00")
    assert deposit.account_id == account.id


@pytest.mark.asyncio
async def test_processed_webhook_idempotency(db_session: AsyncSession) -> None:
    # First webhook record
    hook1 = ProcessedWebhook(
        event_id="evt_unique_123",
        invoice_id="inv_123",
        status="paid",
        paid_amount=Decimal("10.00"),
    )
    db_session.add(hook1)
    await db_session.commit()

    db_session.expunge_all()

    # Duplicate event_id must fail unique primary key constraint
    hook2 = ProcessedWebhook(
        event_id="evt_unique_123",
        invoice_id="inv_123",
        status="paid",
        paid_amount=Decimal("10.00"),
    )
    db_session.add(hook2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_idempotency_record_uniqueness(db_session: AsyncSession) -> None:
    account = Account(api_key_hash="hash_idem_user")
    db_session.add(account)
    await db_session.commit()

    record1 = IdempotencyRecord(
        idempotency_key="key_123",
        account_id=account.id,
        request_hash="hash_req_abc",
        response_status_code=200,
        response_body='{"status": "transferred"}',
    )
    db_session.add(record1)
    await db_session.commit()

    # Expire/detach session objects to test database-level primary key uniqueness
    db_session.expunge_all()

    record2 = IdempotencyRecord(
        idempotency_key="key_123",
        account_id=account.id,
        request_hash="hash_req_different",
        response_status_code=200,
        response_body='{"status": "transferred"}',
    )
    db_session.add(record2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_transaction_ledger(db_session: AsyncSession) -> None:
    account = Account(api_key_hash="hash_txn_user", balance_usd=Decimal("50.00"))
    db_session.add(account)
    await db_session.commit()

    txn = Transaction(
        account_id=account.id,
        type=TransactionType.DEPOSIT.value,
        amount_usd=Decimal("50.00"),
        amount_credits=0,
        balance_usd_after=Decimal("50.00"),
        balance_credits_after=0,
        description="Initial deposit credited",
        reference_id="dep_initial",
    )
    db_session.add(txn)
    await db_session.commit()

    stmt = select(Transaction).where(Transaction.account_id == account.id)
    result = await db_session.scalars(stmt)
    records = list(result.all())

    assert len(records) == 1
    assert records[0].id.startswith("txn_")
    assert records[0].amount_usd == Decimal("50.00")
    assert records[0].type == TransactionType.DEPOSIT.value
