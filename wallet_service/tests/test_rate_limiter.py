from decimal import Decimal

import httpx
import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.core.rate_limiter import rate_limiter
from wallet_service.db.models import Account


@pytest.fixture(autouse=True)
def _reset_limiter():
    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.mark.asyncio
async def test_rate_limit_30_post_allowed_31st_rejected(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    # 1. Setup account with large balance for 30 purchases
    acc_res = await client.post("/v1/accounts")
    api_key = acc_res.json()["api_key"]
    account_id = acc_res.json()["account_id"]

    acc = await db_session.get(Account, account_id)
    assert acc is not None
    acc.balance_usd = Decimal("1000.00")
    await db_session.commit()

    headers = {"X-API-Key": api_key}

    # 2. Fire 30 POST requests
    for i in range(30):
        res = await client.post("/v1/purchases", headers=headers, json={"credits": 1})
        assert res.status_code == status.HTTP_200_OK, f"Request #{i + 1} failed"

    # 3. 31st POST request must be rejected with 429
    res_31 = await client.post("/v1/purchases", headers=headers, json={"credits": 1})
    assert res_31.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert "Retry-After" in res_31.headers

    data = res_31.json()
    assert data["error"]["code"] == "rate_limit_exceeded"
    assert "30 POST requests" in data["error"]["message"]


@pytest.mark.asyncio
async def test_rate_limit_does_not_affect_get_requests(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    acc_res = await client.post("/v1/accounts")
    api_key = acc_res.json()["api_key"]
    account_id = acc_res.json()["account_id"]

    acc = await db_session.get(Account, account_id)
    assert acc is not None
    acc.balance_usd = Decimal("1000.00")
    await db_session.commit()

    headers = {"X-API-Key": api_key}

    # Exhaust the 30 POST quota
    for _ in range(30):
        await client.post("/v1/purchases", headers=headers, json={"credits": 1})

    # GET requests must still succeed (unlimited)
    get_res = await client.get("/v1/accounts/me", headers=headers)
    assert get_res.status_code == status.HTTP_200_OK

    txns_res = await client.get("/v1/transactions", headers=headers)
    assert txns_res.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_rate_limit_webhooks_exempt(
    client: httpx.AsyncClient,
) -> None:
    # Directly test that webhooks endpoint is exempt from POST rate limiting
    for _ in range(35):
        res = await client.post("/v1/webhooks/provider", content=b"{}")
        # Webhook should fail with 401 (missing signature), NOT 429 (rate limit)
        assert res.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_rate_limit_isolated_per_api_key(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    # User 1
    acc1_res = await client.post("/v1/accounts")
    key1 = acc1_res.json()["api_key"]
    id1 = acc1_res.json()["account_id"]

    # User 2
    acc2_res = await client.post("/v1/accounts")
    key2 = acc2_res.json()["api_key"]
    id2 = acc2_res.json()["account_id"]

    acc1 = await db_session.get(Account, id1)
    acc2 = await db_session.get(Account, id2)
    assert acc1 is not None and acc2 is not None
    acc1.balance_usd = Decimal("1000.00")
    acc2.balance_usd = Decimal("1000.00")
    await db_session.commit()

    # Exhaust User 1
    for _ in range(30):
        await client.post(
            "/v1/purchases", headers={"X-API-Key": key1}, json={"credits": 1}
        )

    # User 1 is rate limited
    res1 = await client.post(
        "/v1/purchases", headers={"X-API-Key": key1}, json={"credits": 1}
    )
    assert res1.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    # User 2 can still make requests
    res2 = await client.post(
        "/v1/purchases", headers={"X-API-Key": key2}, json={"credits": 1}
    )
    assert res2.status_code == status.HTTP_200_OK
