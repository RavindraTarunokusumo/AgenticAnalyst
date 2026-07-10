"""LangGraph async Postgres checkpointer integration.

Uses the same PostgreSQL instance (and migration-managed tables) as the
rest of the harness. The checkpointer is the durable execution backbone
for cadence workflows.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from analyst_engine.config import Settings


def _normalize_url_for_checkpointer(database_url: str) -> str:
    """Convert our asyncpg URL to one acceptable by the checkpointer.

    langgraph-checkpoint-postgres works with psycopg (sync/async) or asyncpg
    connection strings. We strip the +asyncpg driver for broadest compatibility.
    """
    if "+asyncpg" in database_url:
        return database_url.replace("+asyncpg", "", 1)
    return database_url


@asynccontextmanager
async def get_async_checkpointer(
    settings: Settings,
) -> AsyncIterator[AsyncPostgresSaver]:
    """Yield a configured AsyncPostgresSaver bound to our database.

    The caller must use it as:
        async with get_async_checkpointer(settings) as cp:
            graph = builder.compile(checkpointer=cp)
            ...
    Setup is idempotent (uses checkpoint_migrations table).
    """
    url = _normalize_url_for_checkpointer(str(settings.database_url))
    # from_conn_string may return an async context manager in this package version.
    # We enter it, run setup (idempotent), and yield the concrete saver.
    raw_saver = AsyncPostgresSaver.from_conn_string(url)
    async with raw_saver as saver:
        await saver.setup()
        yield saver
