"""Async SQLAlchemy engine, session factory, and transaction helpers.

All persistence writes are expected to receive or create a session from here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from analyst_engine.config import Settings


def get_async_engine(settings: Settings, *, echo: bool = False) -> AsyncEngine:
    """Create the async engine from validated Settings.

    The caller owns the engine lifecycle (e.g. dispose on shutdown).
    """
    url = str(settings.database_url)
    engine = create_async_engine(
        url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
    return engine


def get_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to the given engine."""
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Provide a transactional scope around a series of operations.

    Usage:
        async with session_scope(factory) as session:
            ...
    """
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
