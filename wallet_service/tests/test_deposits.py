from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.db.models import Deposit, DepositStatus
from wallet_service.dependencies import get_provider_client
from wallet_service.main import app
from wallet_service.services.provider_client import (
    ProviderInvoiceResponse,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


@pytest.mark.asyncio
async def test_create_deposit_success(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    # 1. Create user account
    acc_res = await client.post("/v1/accounts")
    api_key = acc_res.json()["api_key"]
    account_id = acc_res.json()["account_id"]

    # 2. Mock ProviderClient
    class MockProviderClient:
        async def create_invoice(
            self,
            amount: Decimal,
            external_id: str,
            callback_url: str | None = None,
        ) -> ProviderInvoiceResponse:
            return ProviderInvoiceResponse(
                invoice_id="inv_mock_999",
                status="pending",
                pay_url="http://mock-provider.local/pay/inv_mock_999",
            )

    app.dependency_overrides[get_provider_client] = lambda: MockProviderClient()

    try:
        # 3. Request deposit creation
        dep_res = await client.post(
            "/v1/deposits",
            headers={"X-API-Key": api_key},
            json={"amount": "10.00"},
        )
        assert dep_res.status_code == status.HTTP_201_CREATED
        data = dep_res.json()
        assert data["deposit_id"].startswith("dep_")
        assert data["status"] == DepositStatus.PENDING.value
        assert data["amount"] == "10.00"
        assert data["pay_url"] == "http://mock-provider.local/pay/inv_mock_999"

        deposit_id = data["deposit_id"]

        # 4. Verify record in database
        stmt = select(Deposit).where(Deposit.id == deposit_id)
        deposit = await db_session.scalar(stmt)
        assert deposit is not None
        assert deposit.account_id == account_id
        assert deposit.invoice_id == "inv_mock_999"
        assert deposit.amount == Decimal("10.00")
        assert deposit.status == DepositStatus.PENDING.value
    finally:
        app.dependency_overrides.pop(get_provider_client, None)


@pytest.mark.asyncio
async def test_create_deposit_provider_timeout(client: httpx.AsyncClient) -> None:
    acc_res = await client.post("/v1/accounts")
    api_key = acc_res.json()["api_key"]

    class TimeoutProviderClient:
        async def create_invoice(self, *args: Any, **kwargs: Any) -> ProviderInvoiceResponse:
            raise ProviderTimeoutError()

    app.dependency_overrides[get_provider_client] = lambda: TimeoutProviderClient()

    try:
        dep_res = await client.post(
            "/v1/deposits",
            headers={"X-API-Key": api_key},
            json={"amount": "10.00"},
        )
        assert dep_res.status_code == status.HTTP_504_GATEWAY_TIMEOUT
        data = dep_res.json()
        assert data["error"]["code"] == "provider_timeout"
    finally:
        app.dependency_overrides.pop(get_provider_client, None)


@pytest.mark.asyncio
async def test_create_deposit_provider_unreachable(client: httpx.AsyncClient) -> None:
    acc_res = await client.post("/v1/accounts")
    api_key = acc_res.json()["api_key"]

    class UnreachableProviderClient:
        async def create_invoice(self, *args: Any, **kwargs: Any) -> ProviderInvoiceResponse:
            raise ProviderUnavailableError()

    app.dependency_overrides[get_provider_client] = lambda: UnreachableProviderClient()

    try:
        dep_res = await client.post(
            "/v1/deposits",
            headers={"X-API-Key": api_key},
            json={"amount": "10.00"},
        )
        assert dep_res.status_code == status.HTTP_502_BAD_GATEWAY
        data = dep_res.json()
        assert data["error"]["code"] == "provider_unavailable"
    finally:
        app.dependency_overrides.pop(get_provider_client, None)


@pytest.mark.parametrize("invalid_amount", [
    10.0,       # Float instead of string -> 422
    "0.00",     # Zero amount -> 422
    "-5.00",    # Negative amount -> 422
    "10.5",     # Invalid precision -> 422
])
@pytest.mark.asyncio
async def test_create_deposit_validation_errors(
    client: httpx.AsyncClient,
    invalid_amount: Any,
) -> None:
    acc_res = await client.post("/v1/accounts")
    api_key = acc_res.json()["api_key"]

    dep_res = await client.post(
        "/v1/deposits",
        headers={"X-API-Key": api_key},
        json={"amount": invalid_amount},
    )
    assert dep_res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    data = dep_res.json()
    assert data["error"]["code"] == "validation_error"
