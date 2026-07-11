from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from typing import Protocol

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from analyst_engine.config import Settings
from analyst_engine.domain.models import Cadence, WorkflowRun, WorkflowStatus
from analyst_engine.persistence.engine import get_async_engine, get_session_factory, session_scope
from analyst_engine.persistence.repositories import (
    InvalidWorkflowRunTransitionError,
    create_workflow_run,
    get_workflow_run_by_idempotency,
    update_workflow_run,
)

try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    PostgresContainer = None  # type: ignore[assignment, unused-ignore]


class _ConnectionUrlProvider(Protocol):
    def get_connection_url(self, driver: str | None = None) -> str: ...


class _PostgresContainer(_ConnectionUrlProvider, Protocol):
    def start(self) -> object: ...

    def stop(self) -> object: ...


@pytest.fixture(scope="module")
def workflow_postgres() -> Iterator[_PostgresContainer]:
    if PostgresContainer is None:
        pytest.skip("testcontainers is not installed")
    try:
        container = PostgresContainer(
            image="pgvector/pgvector:0.8.0-pg16",
            username="analyst_test",
            password="testpw",
            dbname="analyst_test",
        )
        container.start()
    except Exception as error:
        pytest.skip(f"Docker is unavailable: {error}")
    try:
        yield container
    finally:
        container.stop()


def _async_database_url(container: _ConnectionUrlProvider) -> str:
    url = container.get_connection_url(driver=None)
    _, separator, connection = url.partition("://")
    if not separator:
        raise ValueError(f"invalid PostgreSQL connection URL: {url!r}")
    return f"postgresql+asyncpg://{connection}"


def test_async_database_url_normalizes_testcontainers_driver() -> None:
    class FakeContainer:
        def get_connection_url(self, driver: str | None = None) -> str:
            return "postgresql+psycopg2://user:password@localhost:5432/database"

    assert _async_database_url(FakeContainer()) == (
        "postgresql+asyncpg://user:password@localhost:5432/database"
    )


def _apply_migrations(database_url: str) -> None:
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        from alembic.config import Config

        from alembic import command

        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old


@pytest.fixture(scope="module")
async def workflow_session_factory(
    workflow_postgres: _PostgresContainer,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = _async_database_url(workflow_postgres)
    _apply_migrations(database_url)
    settings = Settings(
        dashscope_api_key="test-key-for-workflow-run-persistence",
        database_url=database_url,
    )
    engine: AsyncEngine = get_async_engine(settings)
    try:
        yield get_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_illegal_update_preserves_durable_identity_and_status(
    workflow_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    pending = WorkflowRun(cadence=Cadence.DAILY, idempotency_key="daily:illegal-transition")
    async with session_scope(workflow_session_factory) as session:
        created = await create_workflow_run(session, pending)

    with pytest.raises(InvalidWorkflowRunTransitionError):
        async with session_scope(workflow_session_factory) as session:
            await update_workflow_run(
                session,
                created.model_copy(update={"status": WorkflowStatus.SUCCEEDED}),
            )

    async with session_scope(workflow_session_factory) as session:
        durable = await get_workflow_run_by_idempotency(session, created.idempotency_key)

    assert durable is not None
    assert durable.id == created.id
    assert durable.idempotency_key == created.idempotency_key
    assert durable.status == WorkflowStatus.PENDING


@pytest.mark.asyncio
async def test_concurrent_terminal_transition_cannot_overwrite_committed_winner(
    workflow_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    pending = WorkflowRun(cadence=Cadence.DAILY, idempotency_key="daily:terminal-race")
    async with session_scope(workflow_session_factory) as session:
        created = await create_workflow_run(session, pending)
    async with session_scope(workflow_session_factory) as session:
        running = await update_workflow_run(
            session,
            created.model_copy(update={"status": WorkflowStatus.RUNNING}),
        )

    winner_locked = asyncio.Event()
    release_winner = asyncio.Event()
    loser_started = asyncio.Event()

    async def commit_success() -> WorkflowRun:
        async with session_scope(workflow_session_factory) as session:
            succeeded = await update_workflow_run(
                session,
                running.model_copy(update={"status": WorkflowStatus.SUCCEEDED}),
            )
            winner_locked.set()
            await release_winner.wait()
            return succeeded

    async def attempt_failure() -> WorkflowRun:
        await winner_locked.wait()
        loser_started.set()
        async with session_scope(workflow_session_factory) as session:
            return await update_workflow_run(
                session,
                running.model_copy(
                    update={"status": WorkflowStatus.FAILED, "error_summary": "late failure"}
                ),
            )

    winner_task = asyncio.create_task(commit_success())
    loser_task = asyncio.create_task(attempt_failure())
    await loser_started.wait()
    await asyncio.sleep(0.1)
    assert not loser_task.done()
    release_winner.set()

    winner = await winner_task
    with pytest.raises(InvalidWorkflowRunTransitionError):
        await loser_task

    async with session_scope(workflow_session_factory) as session:
        durable = await get_workflow_run_by_idempotency(session, running.idempotency_key)

    assert durable is not None
    assert winner.id == running.id == durable.id
    assert winner.idempotency_key == running.idempotency_key == durable.idempotency_key
    assert durable.status == WorkflowStatus.SUCCEEDED
    assert durable.error_summary is None
