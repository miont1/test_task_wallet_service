from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.db.models import Transaction, TransactionType


@pytest.mark.asyncio
async def test_list_transactions_empty(
    client: httpx.AsyncClient,
) -> None:
    acc_res = await client.post("/v1/accounts")
    api_key = acc_res.json()["api_key"]

    res = await client.get("/v1/transactions", headers={"X-API-Key": api_key})
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["items"] == []
    assert data["has_more"] is False
    assert data["next_cursor"] is None


@pytest.mark.asyncio
async def test_list_transactions_account_isolation(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    # User A
    acc_a_res = await client.post("/v1/accounts")
    key_a = acc_a_res.json()["api_key"]
    id_a = acc_a_res.json()["account_id"]

    # User B
    acc_b_res = await client.post("/v1/accounts")
    id_b = acc_b_res.json()["account_id"]

    txn_a = Transaction(
        account_id=id_a,
        type=TransactionType.DEPOSIT.value,
        amount_usd=Decimal("50.00"),
        amount_credits=0,
        balance_usd_after=Decimal("50.00"),
        balance_credits_after=0,
        description="Deposit A",
    )
    txn_b = Transaction(
        account_id=id_b,
        type=TransactionType.DEPOSIT.value,
        amount_usd=Decimal("100.00"),
        amount_credits=0,
        balance_usd_after=Decimal("100.00"),
        balance_credits_after=0,
        description="Deposit B",
    )
    db_session.add_all([txn_a, txn_b])
    await db_session.commit()

    # User A requests their transactions
    res_a = await client.get("/v1/transactions", headers={"X-API-Key": key_a})
    assert res_a.status_code == status.HTTP_200_OK
    items = res_a.json()["items"]
    assert len(items) == 1
    assert items[0]["description"] == "Deposit A"


@pytest.mark.asyncio
async def test_list_transactions_cursor_pagination(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    acc_res = await client.post("/v1/accounts")
    api_key = acc_res.json()["api_key"]
    account_id = acc_res.json()["account_id"]

    # Seed 5 transactions for account with distinct sequential timestamps
    base_time = datetime(2026, 10, 12, 10, 0, 0, tzinfo=UTC)
    txns = []
    for i in range(1, 6):
        txns.append(
            Transaction(
                id=f"txn_pag_{i:03d}",
                account_id=account_id,
                type=TransactionType.DEPOSIT.value,
                amount_usd=Decimal(f"{i * 10}.00"),
                amount_credits=0,
                balance_usd_after=Decimal(f"{i * 10}.00"),
                balance_credits_after=0,
                description=f"Transaction #{i}",
                created_at=base_time + timedelta(minutes=i),
            )
        )
    db_session.add_all(txns)
    await db_session.commit()

    # Page 1: limit 2
    res1 = await client.get("/v1/transactions?limit=2", headers={"X-API-Key": api_key})
    assert res1.status_code == status.HTTP_200_OK
    page1 = res1.json()
    assert len(page1["items"]) == 2
    assert page1["has_more"] is True
    cursor1 = page1["next_cursor"]
    assert cursor1 is not None

    # Page 2: limit 2 with cursor1
    res2 = await client.get(
        f"/v1/transactions?limit=2&cursor={cursor1}", headers={"X-API-Key": api_key}
    )
    assert res2.status_code == status.HTTP_200_OK
    page2 = res2.json()
    assert len(page2["items"]) == 2
    assert page2["has_more"] is True
    cursor2 = page2["next_cursor"]
    assert cursor2 is not None

    # Page 3: limit 2 with cursor2 (should contain remaining 1 item)
    res3 = await client.get(
        f"/v1/transactions?limit=2&cursor={cursor2}", headers={"X-API-Key": api_key}
    )
    assert res3.status_code == status.HTTP_200_OK
    page3 = res3.json()
    assert len(page3["items"]) == 1
    assert page3["has_more"] is False
    assert page3["next_cursor"] is None

    # Verify no duplicated items across pages
    all_seen_ids = [
        item["id"] for item in page1["items"] + page2["items"] + page3["items"]
    ]
    assert len(all_seen_ids) == 5
    assert len(set(all_seen_ids)) == 5


@pytest.mark.asyncio
async def test_list_transactions_invalid_cursor(
    client: httpx.AsyncClient,
) -> None:
    acc_res = await client.post("/v1/accounts")
    api_key = acc_res.json()["api_key"]

    res = await client.get(
        "/v1/transactions?cursor=totally_bad_cursor", headers={"X-API-Key": api_key}
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert res.json()["error"]["code"] == "invalid_cursor"
