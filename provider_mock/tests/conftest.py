from collections.abc import AsyncIterator

import httpx
import pytest

from provider_mock.config import Settings, get_settings
from provider_mock.main import app
from provider_mock.storage import InvoiceStore, invoice_store


@pytest.fixture(autouse=True)
def clean_invoice_store() -> None:
    """Ensures each test runs with an empty in-memory store."""
    invoice_store.clear()


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def auth_headers(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.api_key}"}


@pytest.fixture
def store() -> InvoiceStore:
    return invoice_store


import pytest_asyncio


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """Test async HTTP client using ASGI transport."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as test_client:
        # Assign shared client into app.state for dependency injection during test
        app.state.http_client = test_client
        yield test_client
