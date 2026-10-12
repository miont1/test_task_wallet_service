import json
from decimal import Decimal

import httpx
import pytest

from provider_mock.config import Settings
from provider_mock.models import InvoiceStatus, WebhookPayload
from provider_mock.webhook import WebhookDispatcher, compute_signature


def test_compute_signature_deterministic() -> None:
    secret = "test-secret-xyz"
    timestamp = 1710000000
    raw_body = '{"event_id":"evt_1","status":"paid"}'

    sig1 = compute_signature(secret, timestamp, raw_body)
    sig2 = compute_signature(secret, timestamp, raw_body)

    assert sig1 == sig2
    assert len(sig1) == 64  # SHA256 hex digest length


def test_signature_changes_with_body_or_timestamp() -> None:
    secret = "test-secret-xyz"
    timestamp = 1710000000
    raw_body = '{"event_id":"evt_1","status":"paid"}'

    sig_orig = compute_signature(secret, timestamp, raw_body)
    sig_diff_time = compute_signature(secret, timestamp + 1, raw_body)
    sig_diff_body = compute_signature(
        secret, timestamp, '{"event_id":"evt_2","status":"paid"}'
    )
    sig_diff_secret = compute_signature("other-secret", timestamp, raw_body)

    assert sig_orig != sig_diff_time
    assert sig_orig != sig_diff_body
    assert sig_orig != sig_diff_secret


@pytest.mark.asyncio
async def test_webhook_dispatch_single(settings: Settings) -> None:
    received_requests = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        received_requests.append(
            {
                "content": request.content.decode(),
                "headers": dict(request.headers),
            }
        )
        return httpx.Response(200, json={"received": True})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        dispatcher = WebhookDispatcher(client=http_client, settings=settings)
        payload = WebhookPayload(
            invoice_id="inv_test",
            status=InvoiceStatus.PAID,
            paid_amount=Decimal("25.00"),
        )

        result = await dispatcher.dispatch(
            callback_url="http://receiver.test/webhook",
            payload=payload,
            duplicate=False,
        )

        assert result.is_delivered is True
        assert result.status_codes == [200]
        assert len(received_requests) == 1

        req = received_requests[0]
        assert "x-signature" in req["headers"]
        assert "x-timestamp" in req["headers"]
        assert req["headers"]["x-signature"].startswith("sha256=")


@pytest.mark.asyncio
async def test_webhook_dispatch_duplicate(settings: Settings) -> None:
    received_requests = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        received_requests.append(
            {
                "content": request.content.decode(),
                "headers": dict(request.headers),
            }
        )
        return httpx.Response(200, json={"received": True})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        dispatcher = WebhookDispatcher(client=http_client, settings=settings)
        payload = WebhookPayload(
            invoice_id="inv_duplicate_test",
            status=InvoiceStatus.PAID,
            paid_amount=Decimal("10.00"),
        )

        result = await dispatcher.dispatch(
            callback_url="http://receiver.test/webhook",
            payload=payload,
            duplicate=True,
        )

        assert len(received_requests) == 2
        assert result.status_codes == [200, 200]

        # Both duplicate requests must have the EXACT same body, event_id, timestamp and signature
        body1 = json.loads(received_requests[0]["content"])
        body2 = json.loads(received_requests[1]["content"])
        assert body1["event_id"] == body2["event_id"]
        assert body1["invoice_id"] == "inv_duplicate_test"

        assert (
            received_requests[0]["headers"]["x-signature"]
            == received_requests[1]["headers"]["x-signature"]
        )
        assert (
            received_requests[0]["headers"]["x-timestamp"]
            == received_requests[1]["headers"]["x-timestamp"]
        )
