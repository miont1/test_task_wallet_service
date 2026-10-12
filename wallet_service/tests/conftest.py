from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from wallet_service.db.session import Base, create_engine_and_factory


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Provides a fresh isolated in-memory SQLite database session for testing."""
    engine, session_factory = create_engine_and_factory("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        yield session

    await engine.dispose()
