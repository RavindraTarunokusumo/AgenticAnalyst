"""Repository integration tests for pipeline bulk lookups and citation checks."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, date, datetime

import pytest
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from alembic import command
from analyst_engine.config import Settings
from analyst_engine.domain.models import (
    Article,
    ArticleBatch,
    BatchSummary,
    Brief,
    Cadence,
    Citation,
    GroupingMethod,
    Source,
)
from analyst_engine.persistence.engine import get_async_engine, get_session_factory, session_scope
from analyst_engine.persistence.repositories import (
    get_articles_by_ids,
    get_sources_by_ids,
    is_batch_summary_cited,
    save_article,
    save_article_batch,
    save_batch_summary,
    save_brief,
    upsert_source,
)

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
        dashscope_api_key="test-key-for-persistence",
        database_url=test_database_url,  # type: ignore[arg-type, unused-ignore]
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
    return session_factory


@pytest.mark.asyncio
async def test_get_articles_by_ids_returns_matching_rows_in_any_order(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    source = Source(
        stable_id="pipeline-src-articles",
        name="Pipeline Source",
        normalized_domain="example.com",
    )
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    articles = [
        Article(
            source_id=source.id,
            url=f"https://example.com/a{i}",
            url_fingerprint=f"fp-a{i}",
            title=f"Article {i}",
            published_at=now,
            cleaned_content=f"Body {i}.",
        )
        for i in range(1, 4)
    ]

    async with session_scope(migrated) as sess:
        await upsert_source(sess, source)
        for article in articles:
            await save_article(sess, article)
        found = await get_articles_by_ids(sess, [articles[2].id, articles[0].id])

    assert {article.id for article in found} == {articles[0].id, articles[2].id}


@pytest.mark.asyncio
async def test_get_articles_by_ids_empty_input_returns_empty_without_query(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(migrated) as sess:
        assert await get_articles_by_ids(sess, []) == []


@pytest.mark.asyncio
async def test_get_sources_by_ids_returns_matching_rows_in_any_order(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    sources = [
        Source(
            stable_id=f"pipeline-src-{index}",
            name=f"Source {index}",
            normalized_domain=f"example{index}.com",
        )
        for index in range(1, 4)
    ]

    async with session_scope(migrated) as sess:
        for source in sources:
            await upsert_source(sess, source)
        found = await get_sources_by_ids(sess, [sources[1].id, sources[0].id])

    assert {source.id for source in found} == {sources[0].id, sources[1].id}


@pytest.mark.asyncio
async def test_get_sources_by_ids_empty_input_returns_empty_without_query(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(migrated) as sess:
        assert await get_sources_by_ids(sess, []) == []


@pytest.mark.asyncio
async def test_is_batch_summary_cited_tracks_daily_citations_only(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    source = Source(
        stable_id="pipeline-src-cited",
        name="Cited Source",
        normalized_domain="example.com",
    )
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    articles = [
        Article(
            source_id=source.id,
            url=f"https://example.com/c{i}",
            url_fingerprint=f"fp-c{i}",
            title=f"Cited Article {i}",
            published_at=now,
            cleaned_content=f"Body {i}.",
        )
        for i in range(1, 4)
    ]
    batch = ArticleBatch(
        article_ids=[article.id for article in articles],
        batch_key="batch:pipeline-cited",
        grouping_method=GroupingMethod.TITLE_TOKEN_JACCARD,
        embedding_model="test-emb",
    )
    summary = BatchSummary(
        batch_id=batch.id,
        model="qwen3.5-flash",
        prompt_version="v1",
        summary="Pipeline summary.",
        citations=[Citation(article_id=articles[0].id, excerpt="Body 1.")],
    )
    daily_brief = Brief(
        cadence=Cadence.DAILY,
        covered_start=date(2026, 7, 12),
        covered_end=date(2026, 7, 12),
        content="Daily brief citing summary.",
        cited_batch_summary_ids=[summary.id],
        cited_article_ids=[articles[0].id],
        created_by_run_id=articles[0].id,
    )
    weekly_brief = Brief(
        cadence=Cadence.WEEKLY,
        covered_start=date(2026, 7, 7),
        covered_end=date(2026, 7, 13),
        content="Weekly brief citing summary.",
        cited_batch_summary_ids=[summary.id],
        cited_article_ids=[articles[0].id],
        created_by_run_id=articles[1].id,
    )

    async with session_scope(migrated) as sess:
        await upsert_source(sess, source)
        for article in articles:
            await save_article(sess, article)
        await save_article_batch(sess, batch)
        await save_batch_summary(sess, summary)
        assert await is_batch_summary_cited(sess, summary.id, Cadence.DAILY) is False
        await save_brief(sess, weekly_brief)
        assert await is_batch_summary_cited(sess, summary.id, Cadence.DAILY) is False
        await save_brief(sess, daily_brief)
        assert await is_batch_summary_cited(sess, summary.id, Cadence.DAILY) is True

        # Excluding the citing brief's own interval must report "not cited" -
        # this is what lets DailyBriefPipeline retry the SAME target_date after
        # its own prior successful run without excluding its own summary.
        assert (
            await is_batch_summary_cited(
                sess,
                summary.id,
                Cadence.DAILY,
                exclude_covered_start=daily_brief.covered_start,
                exclude_covered_end=daily_brief.covered_end,
            )
            is False
        )
        # A DIFFERENT interval's exclusion must not suppress the real citation.
        assert (
            await is_batch_summary_cited(
                sess,
                summary.id,
                Cadence.DAILY,
                exclude_covered_start=date(2026, 6, 1),
                exclude_covered_end=date(2026, 6, 1),
            )
            is True
        )
        assert await is_batch_summary_cited(sess, summary.id, Cadence.WEEKLY) is True
