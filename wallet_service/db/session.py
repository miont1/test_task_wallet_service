from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from wallet_service.config import get_settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""


def create_engine_and_factory(
    database_url: str | None = None,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Creates an async engine and sessionmaker supporting both PostgreSQL and SQLite."""
    url = database_url or get_settings().database_url
    connect_args: dict[str, Any] = {}

    if "sqlite" in url:
        connect_args["check_same_thread"] = False
        engine = create_async_engine(
            url,
            connect_args=connect_args,
        )
    else:
        engine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    return engine, session_factory


# Default application-wide engine and sessionmaker
engine, async_session_factory = create_engine_and_factory()


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db(target_engine: AsyncEngine | None = None) -> None:
    """Helper to create all database tables."""
    eng = target_engine or engine
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
