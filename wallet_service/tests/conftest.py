import os
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.db.session import Base, create_engine_and_factory, get_db_session
from wallet_service.main import app


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Provides an isolated database session for testing.

    Uses TEST_DATABASE_URL if configured (e.g. PostgreSQL in CI), otherwise defaults to in-memory SQLite.
    """
    db_url = os.getenv("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    engine, session_factory = create_engine_and_factory(db_url)

    async with engine.begin() as conn:
        if "sqlite" not in db_url:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        if "sqlite" not in db_url:
            await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    """Provides an async HTTP test client with database dependency override."""

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as test_client:
        app.state.http_client = test_client
        yield test_client

    app.dependency_overrides.pop(get_db_session, None)
