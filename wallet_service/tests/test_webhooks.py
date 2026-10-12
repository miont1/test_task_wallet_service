import json
import time
from decimal import Decimal

import httpx
import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.config import get_settings
from wallet_service.db.models import (
    Account,
    Deposit,
    DepositStatus,
    ProcessedWebhook,
    Transaction,
    TransactionType,
)
from wallet_service.services.webhook_validator import compute_webhook_signature


def make_signed_headers(
    payload_str: str,
    secret: str,
    timestamp: int | None = None,
) -> dict[str, str]:
    ts = int(time.time()) if timestamp is None else timestamp
    sig = compute_webhook_signature(secret, ts, payload_str)
    return {
        "X-Timestamp": str(ts),
        "X-Signature": f"sha256={sig}",
        "Content-Type": "application/json",
    }


@pytest.mark.asyncio
async def test_webhook_paid_success(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    settings = get_settings()

    # 1. Setup account and pending deposit
    acc = Account(id="acc_user_1", api_key_hash="hash1", balance_usd=Decimal("0.00"))
    dep = Deposit(
        id="dep_test_1",
        account_id="acc_user_1",
        invoice_id="inv_test_1",
        amount=Decimal("100.00"),
        status=DepositStatus.PENDING.value,
    )
    db_session.add_all([acc, dep])
    await db_session.commit()

    # 2. Prepare valid paid webhook
    payload = {
        "event_id": "evt_test_1",
        "invoice_id": "inv_test_1",
        "status": "paid",
        "paid_amount": "100.00",
        "occurred_at": "2026-10-12T12:00:00Z",
    }
    payload_bytes = json.dumps(payload)
    headers = make_signed_headers(payload_bytes, settings.provider_webhook_secret)

    # 3. Post webhook
    res = await client.post(
        "/v1/webhooks/provider",
        content=payload_bytes,
        headers=headers,
    )
    assert res.status_code == status.HTTP_200_OK
    assert res.json()["status"] == "ok"

    # 4. Verify DB updates
    await db_session.refresh(dep)
    await db_session.refresh(acc)

    assert dep.status == DepositStatus.PAID.value
    assert dep.fee == Decimal("1.50")
    assert dep.credited_amount == Decimal("98.50")
    assert acc.balance_usd == Decimal("98.50")

    # 5. Verify ledger transaction
    txn_stmt = select(Transaction).where(Transaction.reference_id == dep.id)
    txn = await db_session.scalar(txn_stmt)
    assert txn is not None
    assert txn.account_id == acc.id
    assert txn.type == TransactionType.DEPOSIT.value
    assert txn.amount_usd == Decimal("98.50")
    assert txn.balance_usd_after == Decimal("98.50")

    # 6. Verify webhook deduplication record
    processed = await db_session.get(ProcessedWebhook, "evt_test_1")
    assert processed is not None
    assert processed.invoice_id == "inv_test_1"


@pytest.mark.asyncio
async def test_webhook_partially_paid_success(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    settings = get_settings()

    acc = Account(id="acc_user_2", api_key_hash="hash2", balance_usd=Decimal("10.00"))
    dep = Deposit(
        id="dep_test_2",
        account_id="acc_user_2",
        invoice_id="inv_test_2",
        amount=Decimal("50.00"),
        status=DepositStatus.PENDING.value,
    )
    db_session.add_all([acc, dep])
    await db_session.commit()

    # Partially paid: 30.00 USD -> 1.5% fee = 0.45 USD -> credited = 29.55 USD
    payload = {
        "event_id": "evt_test_2",
        "invoice_id": "inv_test_2",
        "status": "partially_paid",
        "paid_amount": "30.00",
        "occurred_at": "2026-10-12T12:00:00Z",
    }
    payload_str = json.dumps(payload)
    headers = make_signed_headers(payload_str, settings.provider_webhook_secret)

    res = await client.post(
        "/v1/webhooks/provider", content=payload_str, headers=headers
    )
    assert res.status_code == status.HTTP_200_OK

    await db_session.refresh(dep)
    await db_session.refresh(acc)
    assert dep.status == DepositStatus.PARTIALLY_PAID.value
    assert dep.fee == Decimal("0.45")
    assert dep.credited_amount == Decimal("29.55")
    assert acc.balance_usd == Decimal("39.55")


@pytest.mark.asyncio
async def test_webhook_expired_success(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    settings = get_settings()

    acc = Account(id="acc_user_3", api_key_hash="hash3", balance_usd=Decimal("5.00"))
    dep = Deposit(
        id="dep_test_3",
        account_id="acc_user_3",
        invoice_id="inv_test_3",
        amount=Decimal("25.00"),
        status=DepositStatus.PENDING.value,
    )
    db_session.add_all([acc, dep])
    await db_session.commit()

    payload = {
        "event_id": "evt_test_3",
        "invoice_id": "inv_test_3",
        "status": "expired",
        "paid_amount": "0.00",
        "occurred_at": "2026-10-12T12:00:00Z",
    }
    payload_str = json.dumps(payload)
    headers = make_signed_headers(payload_str, settings.provider_webhook_secret)

    res = await client.post(
        "/v1/webhooks/provider", content=payload_str, headers=headers
    )
    assert res.status_code == status.HTTP_200_OK

    await db_session.refresh(dep)
    await db_session.refresh(acc)
    assert dep.status == DepositStatus.EXPIRED.value
    assert dep.fee == Decimal("0.00")
    assert dep.credited_amount == Decimal("0.00")
    assert acc.balance_usd == Decimal("5.00")  # untouched


@pytest.mark.asyncio
async def test_webhook_duplicate_event_id_idempotency(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    settings = get_settings()

    acc = Account(id="acc_user_4", api_key_hash="hash4", balance_usd=Decimal("0.00"))
    dep = Deposit(
        id="dep_test_4",
        account_id="acc_user_4",
        invoice_id="inv_test_4",
        amount=Decimal("100.00"),
        status=DepositStatus.PENDING.value,
    )
    db_session.add_all([acc, dep])
    await db_session.commit()

    payload = {
        "event_id": "evt_test_dedup",
        "invoice_id": "inv_test_4",
        "status": "paid",
        "paid_amount": "100.00",
        "occurred_at": "2026-10-12T12:00:00Z",
    }
    payload_str = json.dumps(payload)
    headers = make_signed_headers(payload_str, settings.provider_webhook_secret)

    # First delivery
    res1 = await client.post(
        "/v1/webhooks/provider", content=payload_str, headers=headers
    )
    assert res1.status_code == status.HTTP_200_OK

    await db_session.refresh(acc)
    assert acc.balance_usd == Decimal("98.50")

    # Second delivery with identical event_id
    res2 = await client.post(
        "/v1/webhooks/provider", content=payload_str, headers=headers
    )
    assert res2.status_code == status.HTTP_200_OK
    assert "Duplicate event already processed" in res2.json()["message"]

    # Balance must NOT be credited a second time!
    await db_session.refresh(acc)
    assert acc.balance_usd == Decimal("98.50")


@pytest.mark.asyncio
async def test_webhook_ignored_if_deposit_already_closed(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    settings = get_settings()

    acc = Account(id="acc_user_5", api_key_hash="hash5", balance_usd=Decimal("100.00"))
    dep = Deposit(
        id="dep_test_5",
        account_id="acc_user_5",
        invoice_id="inv_test_5",
        amount=Decimal("50.00"),
        status=DepositStatus.PAID.value,
        fee=Decimal("0.75"),
        credited_amount=Decimal("49.25"),
    )
    db_session.add_all([acc, dep])
    await db_session.commit()

    # Incoming webhook with new event_id for an already closed deposit
    payload = {
        "event_id": "evt_test_late",
        "invoice_id": "inv_test_5",
        "status": "paid",
        "paid_amount": "50.00",
        "occurred_at": "2026-10-12T12:00:00Z",
    }
    payload_str = json.dumps(payload)
    headers = make_signed_headers(payload_str, settings.provider_webhook_secret)

    res = await client.post(
        "/v1/webhooks/provider", content=payload_str, headers=headers
    )
    assert res.status_code == status.HTTP_200_OK
    assert "already closed" in res.json()["message"]

    await db_session.refresh(acc)
    assert acc.balance_usd == Decimal("100.00")  # untouched


@pytest.mark.asyncio
async def test_webhook_invalid_signature_rejected(
    client: httpx.AsyncClient,
) -> None:
    payload = {
        "event_id": "evt_bad_sig",
        "invoice_id": "inv_any",
        "status": "paid",
        "paid_amount": "10.00",
        "occurred_at": "2026-10-12T12:00:00Z",
    }
    payload_str = json.dumps(payload)
    headers = make_signed_headers(payload_str, "wrong_secret")

    res = await client.post(
        "/v1/webhooks/provider", content=payload_str, headers=headers
    )
    assert res.status_code == status.HTTP_401_UNAUTHORIZED
    assert res.json()["error"]["code"] == "invalid_signature"


@pytest.mark.asyncio
async def test_webhook_expired_timestamp_rejected(
    client: httpx.AsyncClient,
) -> None:
    settings = get_settings()
    payload = {
        "event_id": "evt_old",
        "invoice_id": "inv_any",
        "status": "paid",
        "paid_amount": "10.00",
        "occurred_at": "2026-10-12T12:00:00Z",
    }
    payload_str = json.dumps(payload)
    # Timestamp from 10 minutes ago (> 300s)
    old_timestamp = int(time.time()) - 600
    headers = make_signed_headers(
        payload_str, settings.provider_webhook_secret, timestamp=old_timestamp
    )

    res = await client.post(
        "/v1/webhooks/provider", content=payload_str, headers=headers
    )
    assert res.status_code == status.HTTP_401_UNAUTHORIZED
    assert res.json()["error"]["code"] == "timestamp_expired"


@pytest.mark.asyncio
async def test_webhook_missing_headers_rejected(
    client: httpx.AsyncClient,
) -> None:
    res = await client.post(
        "/v1/webhooks/provider",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_webhook_nonexistent_invoice_not_found(
    client: httpx.AsyncClient,
) -> None:
    settings = get_settings()
    payload = {
        "event_id": "evt_missing_inv",
        "invoice_id": "inv_does_not_exist",
        "status": "paid",
        "paid_amount": "10.00",
        "occurred_at": "2026-10-12T12:00:00Z",
    }
    payload_str = json.dumps(payload)
    headers = make_signed_headers(payload_str, settings.provider_webhook_secret)

    res = await client.post(
        "/v1/webhooks/provider", content=payload_str, headers=headers
    )
    assert res.status_code == status.HTTP_404_NOT_FOUND
    assert res.json()["error"]["code"] == "deposit_not_found"
