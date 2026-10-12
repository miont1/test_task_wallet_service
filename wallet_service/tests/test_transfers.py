from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.db.models import (
    Account,
    IdempotencyRecord,
    Transaction,
    TransactionType,
)


@pytest.mark.asyncio
async def test_transfer_success(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    # 1. Create sender and recipient
    sender_res = await client.post("/v1/accounts")
    sender_key = sender_res.json()["api_key"]
    sender_id = sender_res.json()["account_id"]

    recip_res = await client.post("/v1/accounts")
    recip_id = recip_res.json()["account_id"]

    # Seed sender with initial balance
    sender_acc = await db_session.get(Account, sender_id)
    assert sender_acc is not None
    sender_acc.balance_usd = Decimal("100.00")
    await db_session.commit()

    # 2. Perform transfer
    res = await client.post(
        "/v1/transfers",
        headers={
            "X-API-Key": sender_key,
            "Idempotency-Key": "test_idem_key_1",
        },
        json={"to_account_id": recip_id, "amount": "25.00"},
    )
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["transfer_id"].startswith("trf_")
    assert data["from_account_id"] == sender_id
    assert data["to_account_id"] == recip_id
    assert data["amount"] == "25.00"
    assert data["from_balance_usd_after"] == "75.00"

    # 3. Check balances in DB
    sender_db = await db_session.get(Account, sender_id)
    recip_db = await db_session.get(Account, recip_id)
    assert sender_db is not None and recip_db is not None
    assert sender_db.balance_usd == Decimal("75.00")
    assert recip_db.balance_usd == Decimal("25.00")

    # 4. Check transactions
    txns = (
        await db_session.scalars(
            select(Transaction).where(Transaction.reference_id == data["transfer_id"])
        )
    ).all()
    assert len(txns) == 2
    types = {t.type for t in txns}
    assert types == {
        TransactionType.TRANSFER_OUT.value,
        TransactionType.TRANSFER_IN.value,
    }

    # 5. Check IdempotencyRecord
    record = await db_session.get(IdempotencyRecord, "test_idem_key_1")
    assert record is not None
    assert record.account_id == sender_id


@pytest.mark.asyncio
async def test_transfer_idempotency_replay(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    sender_res = await client.post("/v1/accounts")
    sender_key = sender_res.json()["api_key"]
    sender_id = sender_res.json()["account_id"]

    recip_res = await client.post("/v1/accounts")
    recip_id = recip_res.json()["account_id"]

    sender_acc = await db_session.get(Account, sender_id)
    assert sender_acc is not None
    sender_acc.balance_usd = Decimal("100.00")
    await db_session.commit()

    headers = {
        "X-API-Key": sender_key,
        "Idempotency-Key": "test_replay_key",
    }
    body = {"to_account_id": recip_id, "amount": "30.00"}

    # First request
    res1 = await client.post("/v1/transfers", headers=headers, json=body)
    assert res1.status_code == status.HTTP_200_OK
    data1 = res1.json()

    # Second request with identical payload and key
    res2 = await client.post("/v1/transfers", headers=headers, json=body)
    assert res2.status_code == status.HTTP_200_OK
    data2 = res2.json()

    # Must return identical cached response
    assert data1 == data2

    # Balances must only have been deducted ONCE
    sender_db = await db_session.get(Account, sender_id)
    recip_db = await db_session.get(Account, recip_id)
    assert sender_db is not None and recip_db is not None
    assert sender_db.balance_usd == Decimal("70.00")
    assert recip_db.balance_usd == Decimal("30.00")


@pytest.mark.asyncio
async def test_transfer_idempotency_conflict_different_body(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    sender_res = await client.post("/v1/accounts")
    sender_key = sender_res.json()["api_key"]
    sender_id = sender_res.json()["account_id"]

    recip_res = await client.post("/v1/accounts")
    recip_id = recip_res.json()["account_id"]

    sender_acc = await db_session.get(Account, sender_id)
    assert sender_acc is not None
    sender_acc.balance_usd = Decimal("100.00")
    await db_session.commit()

    headers = {
        "X-API-Key": sender_key,
        "Idempotency-Key": "test_conflict_key",
    }

    # First transfer: 10.00
    res1 = await client.post(
        "/v1/transfers",
        headers=headers,
        json={"to_account_id": recip_id, "amount": "10.00"},
    )
    assert res1.status_code == status.HTTP_200_OK

    # Second transfer with same key but different amount: 20.00 -> 409 Conflict
    res2 = await client.post(
        "/v1/transfers",
        headers=headers,
        json={"to_account_id": recip_id, "amount": "20.00"},
    )
    assert res2.status_code == status.HTTP_409_CONFLICT
    assert res2.json()["error"]["code"] == "idempotency_conflict"

    # Verify balance was only deducted once
    sender_db = await db_session.get(Account, sender_id)
    assert sender_db is not None
    assert sender_db.balance_usd == Decimal("90.00")


@pytest.mark.asyncio
async def test_transfer_insufficient_funds(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    sender_res = await client.post("/v1/accounts")
    sender_key = sender_res.json()["api_key"]
    sender_id = sender_res.json()["account_id"]

    recip_res = await client.post("/v1/accounts")
    recip_id = recip_res.json()["account_id"]

    # Sender balance is 10.00 USD, attempt transfer of 50.00 USD
    sender_acc = await db_session.get(Account, sender_id)
    assert sender_acc is not None
    sender_acc.balance_usd = Decimal("10.00")
    await db_session.commit()

    res = await client.post(
        "/v1/transfers",
        headers={
            "X-API-Key": sender_key,
            "Idempotency-Key": "test_insufficient_funds_key",
        },
        json={"to_account_id": recip_id, "amount": "50.00"},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert res.json()["error"]["code"] == "insufficient_funds"

    # Sender balance untouched
    sender_db = await db_session.get(Account, sender_id)
    assert sender_db is not None
    assert sender_db.balance_usd == Decimal("10.00")


@pytest.mark.asyncio
async def test_transfer_to_self_disallowed(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    sender_res = await client.post("/v1/accounts")
    sender_key = sender_res.json()["api_key"]
    sender_id = sender_res.json()["account_id"]

    res = await client.post(
        "/v1/transfers",
        headers={
            "X-API-Key": sender_key,
            "Idempotency-Key": "test_self_key",
        },
        json={"to_account_id": sender_id, "amount": "10.00"},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert res.json()["error"]["code"] == "self_transfer_not_allowed"


@pytest.mark.asyncio
async def test_transfer_recipient_not_found(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    sender_res = await client.post("/v1/accounts")
    sender_key = sender_res.json()["api_key"]
    sender_id = sender_res.json()["account_id"]

    sender_acc = await db_session.get(Account, sender_id)
    assert sender_acc is not None
    sender_acc.balance_usd = Decimal("50.00")
    await db_session.commit()

    res = await client.post(
        "/v1/transfers",
        headers={
            "X-API-Key": sender_key,
            "Idempotency-Key": "test_missing_recipient_key",
        },
        json={"to_account_id": "acc_does_not_exist", "amount": "10.00"},
    )
    assert res.status_code == status.HTTP_404_NOT_FOUND
    assert res.json()["error"]["code"] == "recipient_not_found"


@pytest.mark.asyncio
async def test_transfer_missing_idempotency_key(
    client: httpx.AsyncClient,
) -> None:
    sender_res = await client.post("/v1/accounts")
    sender_key = sender_res.json()["api_key"]

    res = await client.post(
        "/v1/transfers",
        headers={"X-API-Key": sender_key},
        json={"to_account_id": "acc_any", "amount": "10.00"},
    )
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert res.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "invalid_amount",
    [
        5.0,  # Float -> 422
        "0.00",  # Below 0.01 -> 422
        "-10.00",  # Negative -> 422
        "5.555",  # More than 2 decimal places -> 422
    ],
)
@pytest.mark.asyncio
async def test_transfer_amount_validations(
    client: httpx.AsyncClient,
    invalid_amount: Any,
) -> None:
    sender_res = await client.post("/v1/accounts")
    sender_key = sender_res.json()["api_key"]

    res = await client.post(
        "/v1/transfers",
        headers={
            "X-API-Key": sender_key,
            "Idempotency-Key": "test_invalid_amount_key",
        },
        json={"to_account_id": "acc_any", "amount": invalid_amount},
    )
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.asyncio
async def test_concurrent_mutual_transfers(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    # 1. Setup User A and User B
    acc_a_res = await client.post("/v1/accounts")
    key_a = acc_a_res.json()["api_key"]
    id_a = acc_a_res.json()["account_id"]

    acc_b_res = await client.post("/v1/accounts")
    key_b = acc_b_res.json()["api_key"]
    id_b = acc_b_res.json()["account_id"]

    acc_a = await db_session.get(Account, id_a)
    acc_b = await db_session.get(Account, id_b)
    assert acc_a is not None and acc_b is not None
    acc_a.balance_usd = Decimal("100.00")
    acc_b.balance_usd = Decimal("100.00")
    await db_session.commit()

    # 2. Fire mutual transfers
    res_a = await client.post(
        "/v1/transfers",
        headers={"X-API-Key": key_a, "Idempotency-Key": "concurrent_key_a"},
        json={"to_account_id": id_b, "amount": "15.00"},
    )
    res_b = await client.post(
        "/v1/transfers",
        headers={"X-API-Key": key_b, "Idempotency-Key": "concurrent_key_b"},
        json={"to_account_id": id_a, "amount": "25.00"},
    )

    assert res_a.status_code == status.HTTP_200_OK
    assert res_b.status_code == status.HTTP_200_OK

    await db_session.refresh(acc_a)
    await db_session.refresh(acc_b)

    # User A: 100 - 15 + 25 = 110.00
    # User B: 100 + 15 - 25 = 90.00
    assert acc_a.balance_usd == Decimal("110.00")
    assert acc_b.balance_usd == Decimal("90.00")
