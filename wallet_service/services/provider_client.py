import logging
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel

from wallet_service.config import Settings, get_settings
from wallet_service.core.errors import (
    ProviderBadResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

logger = logging.getLogger(__name__)


class ProviderInvoiceResponse(BaseModel):
    invoice_id: str
    status: str
    pay_url: str


class ProviderClient:
    """Async HTTP client for calling the provider-mock payment service."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings | None = None,
    ) -> None:
        self._client = client
        self._settings = settings or get_settings()

    async def create_invoice(
        self,
        amount: Decimal,
        external_id: str,
        callback_url: str | None = None,
    ) -> ProviderInvoiceResponse:
        """Calls POST /invoices on provider-mock with timeouts and error handling."""
        target_url = f"{self._settings.provider_base_url.rstrip('/')}/invoices"
        headers = {
            "Authorization": f"Bearer {self._settings.provider_api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "amount": f"{amount:.2f}",
            "currency": "USD",
            "external_id": external_id,
            "callback_url": callback_url or self._settings.callback_url,
        }

        try:
            response = await self._client.post(
                target_url,
                json=payload,
                headers=headers,
                timeout=self._settings.provider_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            logger.error("Provider request timed out for external_id %s: %s", external_id, exc)
            raise ProviderTimeoutError() from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            logger.error("Provider connection failed for external_id %s: %s", external_id, exc)
            raise ProviderUnavailableError() from exc

        if response.status_code != 201:
            logger.error(
                "Provider returned unexpected status %s for external_id %s: %s",
                response.status_code,
                external_id,
                response.text,
            )
            details = None
            try:
                details = response.json()
            except ValueError:
                details = {"raw_response": response.text}

            raise ProviderBadResponseError(
                message=f"Provider failed with HTTP {response.status_code}",
                details=details,
            )

        data = response.json()
        return ProviderInvoiceResponse(
            invoice_id=data["invoice_id"],
            status=data["status"],
            pay_url=data["pay_url"],
        )
