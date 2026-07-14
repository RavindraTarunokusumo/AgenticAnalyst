"""PostgreSQL integration tests for ingestion race handling."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from fixtures import truncate_domain_tables  # type: ignore[import-not-found]
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from alembic import command
from analyst_engine.config import Settings
from analyst_engine.domain.models import ExtractorKind, IngestionStatus, Source
from analyst_engine.ingestion.models import ExtractedArticle
from analyst_engine.ingestion.service import IngestionService
from analyst_engine.persistence.engine import get_async_engine, get_session_factory, session_scope
from analyst_engine.persistence.models import Article as ORMArticle
from analyst_engine.persistence.models import IngestionAttempt as ORMIngestionAttempt
from analyst_engine.persistence.repositories import upsert_source

try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    PostgresContainer = None  # type: ignore[import-untyped, unused-ignore]


pytestmark = pytest.mark.integration


def _docker_endpoint_available() -> bool:
    client = None
    try:
        import docker

        client = docker.from_env(timeout=3)  # type: ignore[attr-defined, unused-ignore]
        client.ping()
        return True
    except Exception:
        return False
    finally:
        if client is not None:
            with suppress(Exception):
                client.close()


@pytest.fixture(scope="session")
def pg_container():  # type: ignore[no-untyped-def, unused-ignore]
    if os.environ.get("DATABASE_URL"):
        yield None
        return
    if PostgresContainer is None:
        pytest.skip("integration database unavailable: no DATABASE_URL or testcontainers")
    if not _docker_endpoint_available():
        pytest.skip("integration database unavailable: Docker endpoint not found")
    container = PostgresContainer(
        image="pgvector/pgvector:0.8.0-pg16",
        username="analyst_test",
        password="testpw",
        dbname="analyst_test",
    )
    try:
        container.start()
    except Exception:
        with suppress(Exception):
            container.stop()
        raise
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def test_database_url(pg_container) -> str:  # type: ignore[no-untyped-def, unused-ignore]
    base = os.environ.get("DATABASE_URL")
    if base is None:
        base = pg_container.get_connection_url(driver=None)
    _, separator, connection = base.partition("://")
    if not separator:
        raise ValueError(f"invalid PostgreSQL connection URL: {base!r}")
    return f"postgresql+asyncpg://{connection}"


@pytest.fixture(scope="session")
def test_settings(test_database_url: str) -> Settings:
    return Settings(
        dashscope_api_key="test-key-for-ingestion-concurrency",
        database_url=test_database_url,  # type: ignore[arg-type, unused-ignore]
        article_min_content_length=50,
    )


@pytest.fixture
async def engine(test_settings: Settings) -> AsyncIterator[AsyncEngine]:
    eng = get_async_engine(test_settings)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return get_session_factory(engine)


async def _apply_migrations(database_url: str) -> None:
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        cfg = Config("alembic.ini")
        command.upgrade(cfg, "head")
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old


@pytest.fixture
async def migrated(
    test_database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> async_sessionmaker[AsyncSession]:
    await _apply_migrations(test_database_url)
    await truncate_domain_tables(session_factory)
    return session_factory


_ARTICLE_URL = "https://93.184.216.34/race-article.html"
_CONTENT = "Concurrent ingestion race article body with enough cleaned text."


class _RaceExtractor:
    async def extract(self, url: str) -> ExtractedArticle:
        return ExtractedArticle(
            url=url,
            title="Race Article",
            text=_CONTENT,
            language="en",
            extractor=ExtractorKind.PRIMARY_HTTP,
            raw_content_hash="race-hash",
            published_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
            author="Race Author",
        )


class _UnusedFeedClient:
    async def fetch(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("feed client should not be used in this test")


@pytest.mark.asyncio
async def test_concurrent_duplicate_url_ingestion_records_one_article_and_mixed_attempts(
    migrated: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    source_id = uuid4()
    async with session_scope(migrated) as session:
        await upsert_source(
            session,
            Source(
                id=source_id,
                stable_id="race-source",
                name="Race Source",
                normalized_domain="example.com",
            ),
        )

    service = IngestionService(
        session_factory=migrated,
        feed_client=_UnusedFeedClient(),  # type: ignore[arg-type]
        primary_extractor=_RaceExtractor(),
        fallback_extractor=_RaceExtractor(),
        settings=test_settings,
        clock=lambda: datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    )

    results = await asyncio.gather(
        service.ingest_urls(source_id, [_ARTICLE_URL]),
        service.ingest_urls(source_id, [_ARTICLE_URL]),
    )
    flat_results = [item for batch in results for item in batch]

    assert len(flat_results) == 2
    statuses = {result.status for result in flat_results}
    assert statuses == {IngestionStatus.SUCCEEDED, IngestionStatus.DUPLICATE}

    async with session_scope(migrated) as session:
        article_count = (
            await session.execute(select(func.count()).select_from(ORMArticle))
        ).scalar_one()
        succeeded_count = (
            await session.execute(
                select(func.count())
                .select_from(ORMIngestionAttempt)
                .where(ORMIngestionAttempt.status == IngestionStatus.SUCCEEDED.value)
            )
        ).scalar_one()
        duplicate_count = (
            await session.execute(
                select(func.count())
                .select_from(ORMIngestionAttempt)
                .where(ORMIngestionAttempt.status == IngestionStatus.DUPLICATE.value)
            )
        ).scalar_one()

    assert article_count == 1
    assert succeeded_count == 1
    assert duplicate_count == 1

    article_ids = {result.article_id for result in flat_results}
    assert len(article_ids) == 1
    assert None not in article_ids
    assert isinstance(next(iter(article_ids)), UUID)
