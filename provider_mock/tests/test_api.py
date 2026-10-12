from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import status

from provider_mock.dependencies import get_webhook_dispatcher
from provider_mock.main import app
from provider_mock.models import InvoiceStatus, WebhookPayload
from provider_mock.webhook import WebhookDeliveryResult


@pytest.mark.asyncio
async def test_health_check(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_auth_missing_or_invalid_token(client: httpx.AsyncClient) -> None:
    # 1. Missing Authorization header
    res1 = await client.post("/invoices", json={
        "amount": "10.00",
        "currency": "USD",
        "external_id": "dep_1",
        "callback_url": "http://callback.test",
    })
    assert res1.status_code == status.HTTP_401_UNAUTHORIZED
    assert res1.json()["error"]["code"] == "unauthorized"

    # 2. Invalid Bearer token
    res2 = await client.post(
        "/invoices",
        headers={"Authorization": "Bearer wrong-token-value"},
        json={
            "amount": "10.00",
            "currency": "USD",
            "external_id": "dep_1",
            "callback_url": "http://callback.test",
        },
    )
    assert res2.status_code == status.HTTP_401_UNAUTHORIZED
    assert res2.json()["error"]["code"] == "invalid_token"


@pytest.mark.asyncio
async def test_create_invoice_success(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    payload = {
        "amount": "10.00",
        "currency": "USD",
        "external_id": "dep_success_1",
        "callback_url": "http://wallet-service:8000/v1/webhooks/provider",
    }
    response = await client.post("/invoices", headers=auth_headers, json=payload)
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    assert data["invoice_id"].startswith("inv_")
    assert data["status"] == "pending"
    assert data["pay_url"].endswith(data["invoice_id"])


@pytest.mark.parametrize("invalid_amount", [
    10.0,       # Float instead of string
    10,         # Int instead of string
    "10.5",     # Only 1 decimal place
    "10.005",   # 3 decimal places
    "-10.00",   # Negative amount
    "abc",      # Non-numeric string
])
@pytest.mark.asyncio
async def test_create_invoice_invalid_amount_validation(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    invalid_amount: Any,
) -> None:
    payload = {
        "amount": invalid_amount,
        "currency": "USD",
        "external_id": "dep_err_1",
        "callback_url": "http://callback.test",
    }
    response = await client.post("/invoices", headers=auth_headers, json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    data = response.json()
    assert data["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_get_invoice_detail(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    # Create invoice first
    create_res = await client.post("/invoices", headers=auth_headers, json={
        "amount": "25.50",
        "currency": "USD",
        "external_id": "dep_get_1",
        "callback_url": "http://callback.test",
    })
    invoice_id = create_res.json()["invoice_id"]

    # Get invoice
    get_res = await client.get(f"/invoices/{invoice_id}", headers=auth_headers)
    assert get_res.status_code == status.HTTP_200_OK

    data = get_res.json()
    assert data["invoice_id"] == invoice_id
    assert data["status"] == "pending"
    assert data["amount"] == "25.50"
    assert data["paid_amount"] == "0.00"
    assert data["currency"] == "USD"
    assert data["external_id"] == "dep_get_1"


@pytest.mark.asyncio
async def test_get_nonexistent_invoice(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    res = await client.get("/invoices/inv_nonexistent", headers=auth_headers)
    assert res.status_code == status.HTTP_404_NOT_FOUND
    assert res.json()["error"]["code"] == "invoice_not_found"


@pytest.mark.asyncio
async def test_simulate_invoice_and_webhook_dispatch(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    # 1. Create invoice
    create_res = await client.post("/invoices", headers=auth_headers, json={
        "amount": "10.00",
        "currency": "USD",
        "external_id": "dep_sim_1",
        "callback_url": "http://receiver.test/webhook",
    })
    invoice_id = create_res.json()["invoice_id"]

    # 2. Mock dispatcher using dependency override
    dispatched_calls: list[dict[str, Any]] = []

    class MockDispatcher:
        async def dispatch(
            self,
            callback_url: str,
            payload: WebhookPayload,
            duplicate: bool = False,
        ) -> WebhookDeliveryResult:
            dispatched_calls.append({
                "callback_url": callback_url,
                "payload": payload,
                "duplicate": duplicate,
            })
            status_codes = [200, 200] if duplicate else [200]
            return WebhookDeliveryResult(status_codes=status_codes, errors=[])

    app.dependency_overrides[get_webhook_dispatcher] = lambda: MockDispatcher()

    try:
        # 3. Simulate payment with deliver_webhook=True and duplicate=True
        sim_res = await client.post(
            f"/invoices/{invoice_id}/simulate",
            headers=auth_headers,
            json={
                "status": "paid",
                "paid_amount": "10.00",
                "deliver_webhook": True,
                "duplicate": True,
            },
        )
        assert sim_res.status_code == status.HTTP_200_OK
        data = sim_res.json()
        assert data["invoice_id"] == invoice_id
        assert data["status"] == "paid"
        assert data["paid_amount"] == "10.00"
        assert data["webhook_delivered"] is True
        assert data["webhook_duplicate"] is True
        assert data["webhook_status_codes"] == [200, 200]

        # Verify mocked dispatch call
        assert len(dispatched_calls) == 1
        assert dispatched_calls[0]["callback_url"] == "http://receiver.test/webhook"
        assert dispatched_calls[0]["payload"].status == InvoiceStatus.PAID
        assert dispatched_calls[0]["payload"].paid_amount == Decimal("10.00")
        assert dispatched_calls[0]["duplicate"] is True
    finally:
        app.dependency_overrides.pop(get_webhook_dispatcher, None)


@pytest.mark.asyncio
async def test_simulate_already_final_invoice_returns_409(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    # 1. Create invoice
    create_res = await client.post("/invoices", headers=auth_headers, json={
        "amount": "10.00",
        "currency": "USD",
        "external_id": "dep_final_1",
        "callback_url": "http://callback.test",
    })
    invoice_id = create_res.json()["invoice_id"]

    # 2. Simulate to paid
    await client.post(
        f"/invoices/{invoice_id}/simulate",
        headers=auth_headers,
        json={"status": "paid", "paid_amount": "10.00", "deliver_webhook": False},
    )

    # 3. Attempt to simulate again -> 409 Conflict
    second_sim = await client.post(
        f"/invoices/{invoice_id}/simulate",
        headers=auth_headers,
        json={"status": "expired", "paid_amount": "0.00", "deliver_webhook": False},
    )
    assert second_sim.status_code == status.HTTP_409_CONFLICT
    assert second_sim.json()["error"]["code"] == "invoice_already_final"
