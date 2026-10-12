import hashlib
import hmac
import logging
import time

import httpx

from provider_mock.config import Settings, get_settings
from provider_mock.models import WebhookPayload

logger = logging.getLogger(__name__)


def compute_signature(secret: str, timestamp: int | str, raw_body: str) -> str:
    """Computes HMAC-SHA256 signature for the webhook payload.

    Formula from specification: HMAC-SHA256(secret, f"{timestamp}.{raw_body}")
    Returns hex digest string.
    """
    message = f"{timestamp}.{raw_body}".encode()
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=message,
        digestmod=hashlib.sha256,
    ).hexdigest()


class WebhookDeliveryResult:
    def __init__(self, status_codes: list[int], errors: list[str]) -> None:
        self.status_codes = status_codes
        self.errors = errors

    @property
    def is_delivered(self) -> bool:
        return any(200 <= code < 300 for code in self.status_codes)


class WebhookDispatcher:
    """Dispatches outgoing signed webhooks using an injected shared HTTP client."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings | None = None,
    ) -> None:
        self._client = client
        self._settings = settings or get_settings()

    async def dispatch(
        self,
        callback_url: str,
        payload: WebhookPayload,
        duplicate: bool = False,
    ) -> WebhookDeliveryResult:
        """Sends the webhook to callback_url with signature headers.

        Always uses the injected shared client to preserve connection pooling.
        If duplicate=True, sends the exact same payload with identical headers twice.
        """
        timestamp = int(time.time())
        raw_body = payload.model_dump_json()
        sig_hex = compute_signature(
            secret=self._settings.webhook_secret,
            timestamp=timestamp,
            raw_body=raw_body,
        )

        headers = {
            "Content-Type": "application/json",
            "X-Timestamp": str(timestamp),
            "X-Signature": f"sha256={sig_hex}",
        }

        iterations = 2 if duplicate else 1
        status_codes: list[int] = []
        errors: list[str] = []

        async def _send_single() -> None:
            try:
                response = await self._client.post(
                    callback_url,
                    content=raw_body,
                    headers=headers,
                )
                status_codes.append(response.status_code)
                logger.info(
                    "Webhook sent to %s for invoice %s: HTTP %s",
                    callback_url,
                    payload.invoice_id,
                    response.status_code,
                )
            except httpx.RequestError as exc:
                logger.error(
                    "Webhook delivery failed for invoice %s: %s",
                    payload.invoice_id,
                    str(exc),
                )
                errors.append(str(exc))
                status_codes.append(0)

        for _ in range(iterations):
            await _send_single()

        return WebhookDeliveryResult(status_codes=status_codes, errors=errors)
