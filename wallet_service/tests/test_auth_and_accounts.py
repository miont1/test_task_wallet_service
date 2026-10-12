import httpx
import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.core.security import hash_api_key
from wallet_service.db.models import Account


@pytest.mark.asyncio
async def test_health_check(client: httpx.AsyncClient) -> None:
    res = await client.get("/health")
    assert res.status_code == status.HTTP_200_OK
    assert res.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_create_account_and_key_security(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    # 1. Create account via POST /v1/accounts
    res = await client.post("/v1/accounts")
    assert res.status_code == status.HTTP_201_CREATED

    data = res.json()
    assert data["account_id"].startswith("acc_")
    assert data["api_key"].startswith("wlt_")
    assert data["balance_usd"] == "0.00"
    assert data["balance_credits"] == 0

    raw_api_key = data["api_key"]
    account_id = data["account_id"]

    # 2. Verify that database stores ONLY SHA-256 hash, NEVER plaintext key
    stmt = select(Account).where(Account.id == account_id)
    account = await db_session.scalar(stmt)
    assert account is not None
    assert account.api_key_hash == hash_api_key(raw_api_key)
    assert raw_api_key not in account.api_key_hash
    assert len(account.api_key_hash) == 64


@pytest.mark.asyncio
async def test_get_my_account_authorized(client: httpx.AsyncClient) -> None:
    # 1. Create account
    create_res = await client.post("/v1/accounts")
    assert create_res.status_code == status.HTTP_201_CREATED
    data = create_res.json()
    api_key = data["api_key"]
    account_id = data["account_id"]

    # 2. Get me with valid X-API-Key
    me_res = await client.get("/v1/accounts/me", headers={"X-API-Key": api_key})
    assert me_res.status_code == status.HTTP_200_OK
    me_data = me_res.json()
    assert me_data["account_id"] == account_id
    assert me_data["balance_usd"] == "0.00"
    assert me_data["balance_credits"] == 0


@pytest.mark.asyncio
async def test_get_my_account_missing_header_returns_401(
    client: httpx.AsyncClient,
) -> None:
    res = await client.get("/v1/accounts/me")
    assert res.status_code == status.HTTP_401_UNAUTHORIZED
    data = res.json()
    assert "error" in data
    assert data["error"]["code"] == "missing_api_key"


@pytest.mark.asyncio
async def test_get_my_account_invalid_key_returns_401(
    client: httpx.AsyncClient,
) -> None:
    res = await client.get(
        "/v1/accounts/me", headers={"X-API-Key": "wlt_completely_fake_key"}
    )
    assert res.status_code == status.HTTP_401_UNAUTHORIZED
    data = res.json()
    assert "error" in data
    assert data["error"]["code"] == "invalid_api_key"
