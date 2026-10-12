from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.db.models import Account, Transaction, TransactionType


@pytest.mark.asyncio
async def test_purchase_credits_base_tier(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    # 1. Create account and seed balance
    acc_res = await client.post("/v1/accounts")
    api_key = acc_res.json()["api_key"]
    account_id = acc_res.json()["account_id"]

    acc = await db_session.get(Account, account_id)
    assert acc is not None
    acc.balance_usd = Decimal("50.00")
    await db_session.commit()

    # 2. Buy 333 credits -> 33.30 USD
    res = await client.post(
        "/v1/purchases",
        headers={"X-API-Key": api_key},
        json={"credits": 333},
    )
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["purchase_id"].startswith("pur_")
    assert data["credits_purchased"] == 333
    assert data["cost_usd"] == "33.30"
    assert data["balance_usd_after"] == "16.70"
    assert data["balance_credits_after"] == 333

    # 3. Check DB state
    await db_session.refresh(acc)
    assert acc.balance_usd == Decimal("16.70")
    assert acc.balance_credits == 333

    # 4. Check ledger transaction
    txn_stmt = select(Transaction).where(
        Transaction.reference_id == data["purchase_id"]
    )
    txn = await db_session.scalar(txn_stmt)
    assert txn is not None
    assert txn.type == TransactionType.PURCHASE.value
    assert txn.amount_usd == Decimal("33.30")
    assert txn.amount_credits == 333
    assert txn.balance_usd_after == Decimal("16.70")
    assert txn.balance_credits_after == 333


@pytest.mark.asyncio
async def test_purchase_credits_tier_1_discount(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    acc_res = await client.post("/v1/accounts")
    api_key = acc_res.json()["api_key"]
    account_id = acc_res.json()["account_id"]

    acc = await db_session.get(Account, account_id)
    assert acc is not None
    acc.balance_usd = Decimal("100.00")
    await db_session.commit()

    # 507 credits -> 5% discount = 48.17 USD
    res = await client.post(
        "/v1/purchases",
        headers={"X-API-Key": api_key},
        json={"credits": 507},
    )
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["credits_purchased"] == 507
    assert data["cost_usd"] == "48.17"
    assert data["balance_usd_after"] == "51.83"
    assert data["balance_credits_after"] == 507


@pytest.mark.asyncio
async def test_purchase_credits_tier_2_discount(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    acc_res = await client.post("/v1/accounts")
    api_key = acc_res.json()["api_key"]
    account_id = acc_res.json()["account_id"]

    acc = await db_session.get(Account, account_id)
    assert acc is not None
    acc.balance_usd = Decimal("100.00")
    await db_session.commit()

    # 1005 credits -> 12.5% discount = 87.94 USD
    res = await client.post(
        "/v1/purchases",
        headers={"X-API-Key": api_key},
        json={"credits": 1005},
    )
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["credits_purchased"] == 1005
    assert data["cost_usd"] == "87.94"
    assert data["balance_usd_after"] == "12.06"
    assert data["balance_credits_after"] == 1005


@pytest.mark.asyncio
async def test_purchase_credits_insufficient_funds(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    acc_res = await client.post("/v1/accounts")
    api_key = acc_res.json()["api_key"]
    account_id = acc_res.json()["account_id"]

    acc = await db_session.get(Account, account_id)
    assert acc is not None
    acc.balance_usd = Decimal("10.00")
    await db_session.commit()

    # Needs 33.30 USD, only has 10.00 USD
    res = await client.post(
        "/v1/purchases",
        headers={"X-API-Key": api_key},
        json={"credits": 333},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    data = res.json()
    assert data["error"]["code"] == "insufficient_funds"

    await db_session.refresh(acc)
    assert acc.balance_usd == Decimal("10.00")
    assert acc.balance_credits == 0


@pytest.mark.parametrize(
    "invalid_credits",
    [
        0,
        -10,
        "abc",
        50.5,
    ],
)
@pytest.mark.asyncio
async def test_purchase_credits_validation_errors(
    client: httpx.AsyncClient,
    invalid_credits: Any,
) -> None:
    acc_res = await client.post("/v1/accounts")
    api_key = acc_res.json()["api_key"]

    res = await client.post(
        "/v1/purchases",
        headers={"X-API-Key": api_key},
        json={"credits": invalid_credits},
    )
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
