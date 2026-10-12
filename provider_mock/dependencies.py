from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from provider_mock.config import Settings, get_settings
from provider_mock.storage import InvoiceStore, invoice_store
from provider_mock.webhook import WebhookDispatcher

http_bearer_scheme = HTTPBearer(auto_error=False)


def get_invoice_store() -> InvoiceStore:
    return invoice_store


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Retrieves the shared httpx.AsyncClient from FastAPI application state.

    This ensures TCP connection pooling across all requests.
    """
    client: httpx.AsyncClient | None = getattr(request.app.state, "http_client", None)
    if client is None:
        raise RuntimeError("Application HTTP client has not been initialized")
    return client


def get_webhook_dispatcher(
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> WebhookDispatcher:
    return WebhookDispatcher(client=client, settings=settings)


def verify_bearer_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(http_bearer_scheme)
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    """Verifies that requests to provider-mock supply a valid Bearer token."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "unauthorized",
                    "message": "Missing or invalid Authorization header",
                }
            },
        )
    if credentials.credentials != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "invalid_token",
                    "message": "Invalid provider API key",
                }
            },
        )
    return credentials.credentials
