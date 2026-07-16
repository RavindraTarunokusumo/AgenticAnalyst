"""Repository integration tests for API-layer lookups."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic.config import Config
from fixtures import truncate_domain_tables  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from alembic import command
from analyst_engine.config import Settings
from analyst_engine.domain.models import (
    Article,
    ArticleBatch,
    BatchSummary,
    Citation,
    GroupingMethod,
    IngestionAttempt,
    IngestionStatus,
    Source,
    SourceFeed,
    Topic,
)
from analyst_engine.persistence.engine import get_async_engine, get_session_factory, session_scope
from analyst_engine.persistence.repositories import (
    create_topic,
    get_batch_summaries_by_ids,
    list_ingestion_attempts,
    list_source_feeds_for_source,
    record_ingestion_attempt,
    save_article,
    save_article_batch,
    save_batch_summary,
    upsert_source,
    upsert_source_feed,
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
    await truncate_domain_tables(session_factory)
    return session_factory


@pytest.mark.asyncio
async def test_list_source_feeds_for_source_orders_by_url_and_includes_disabled(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    source = Source(
        stable_id="api-src-feeds",
        name="API Feeds Source",
        normalized_domain="example.com",
    )
    feeds = [
        SourceFeed(
            source_id=source.id,
            feed_url="https://example.com/z-feed.xml",
            feed_url_fingerprint="feed-fp-z",
            enabled=True,
            poll_interval_minutes=60,
        ),
        SourceFeed(
            source_id=source.id,
            feed_url="https://example.com/a-feed.xml",
            feed_url_fingerprint="feed-fp-a",
            enabled=False,
            poll_interval_minutes=30,
        ),
    ]

    async with session_scope(migrated) as sess:
        await upsert_source(sess, source)
        for feed in feeds:
            await upsert_source_feed(sess, feed)
        listed = await list_source_feeds_for_source(sess, source.id)
        empty = await list_source_feeds_for_source(sess, uuid4())

    assert [feed.feed_url for feed in listed] == [
        "https://example.com/a-feed.xml",
        "https://example.com/z-feed.xml",
    ]
    assert {feed.enabled for feed in listed} == {True, False}
    assert empty == []


@pytest.mark.asyncio
async def test_record_source_less_ingestion_attempt_round_trips(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    """Regression: pasted-link / upload attempts have topic_id and null source_id.

    T5 domain allowed source_id=None, but the ORM/migration left the column
    NOT NULL. Unit tests that fake persistence never hit Postgres; this test
    exercises the real repository path.
    """
    topic = Topic(
        name="Direct-add topic",
        description="Topic for source-less ingestion attempts",
        keywords=["direct", "paste"],
    )
    attempt = IngestionAttempt(
        topic_id=topic.id,
        source_id=None,
        requested_url="https://example.com/pasted-link",
        canonical_url="https://example.com/pasted-link",
        url_fingerprint="fp-pasted-link",
        status=IngestionStatus.SUCCEEDED,
        started_at=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
        completed_at=datetime(2026, 7, 16, 12, 0, 1, tzinfo=UTC),
    )

    async with session_scope(migrated) as sess:
        await create_topic(sess, topic)
        saved = await record_ingestion_attempt(sess, attempt)
        listed = await list_ingestion_attempts(sess, limit=10)

    assert saved.id == attempt.id
    assert saved.topic_id == topic.id
    assert saved.source_id is None
    assert saved.requested_url == "https://example.com/pasted-link"
    assert saved.status is IngestionStatus.SUCCEEDED
    assert len(listed) == 1
    assert listed[0].id == attempt.id
    assert listed[0].source_id is None
    assert listed[0].topic_id == topic.id


@pytest.mark.asyncio
async def test_list_ingestion_attempts_filters_status_orders_newest_first_and_clamps_limit(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    source = Source(
        stable_id="api-src-attempts",
        name="API Attempts Source",
        normalized_domain="example.com",
    )
    base_time = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    attempts = [
        IngestionAttempt(
            source_id=source.id,
            requested_url="https://example.com/old",
            status=IngestionStatus.SUCCEEDED,
            started_at=base_time,
        ),
        IngestionAttempt(
            source_id=source.id,
            requested_url="https://example.com/new",
            status=IngestionStatus.SUCCEEDED,
            started_at=base_time + timedelta(hours=1),
        ),
        IngestionAttempt(
            source_id=source.id,
            requested_url="https://example.com/failed",
            status=IngestionStatus.FAILED,
            started_at=base_time + timedelta(hours=2),
        ),
    ]

    async with session_scope(migrated) as sess:
        await upsert_source(sess, source)
        for attempt in attempts:
            await record_ingestion_attempt(sess, attempt)
        all_attempts = await list_ingestion_attempts(sess, limit=10)
        succeeded = await list_ingestion_attempts(sess, status=IngestionStatus.SUCCEEDED, limit=1)
        clamped = await list_ingestion_attempts(sess, limit=500)

    assert [attempt.requested_url for attempt in all_attempts] == [
        "https://example.com/failed",
        "https://example.com/new",
        "https://example.com/old",
    ]
    assert len(succeeded) == 1
    assert succeeded[0].status == IngestionStatus.SUCCEEDED
    assert len(clamped) == 3


@pytest.mark.asyncio
async def test_get_batch_summaries_by_ids_bulk_lookup_and_empty_input(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    source = Source(
        stable_id="api-src-summaries",
        name="API Summaries Source",
        normalized_domain="example.com",
    )
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    articles = [
        Article(
            source_id=source.id,
            url=f"https://example.com/s{i}",
            url_fingerprint=f"fp-s{i}",
            title=f"Summary Article {i}",
            published_at=now,
            cleaned_content=f"Body {i}.",
        )
        for i in range(1, 4)
    ]
    batch = ArticleBatch(
        article_ids=[article.id for article in articles],
        batch_key="batch:api-summaries",
        grouping_method=GroupingMethod.TITLE_TOKEN_JACCARD,
        embedding_model="test-emb",
    )
    summaries = [
        BatchSummary(
            batch_id=batch.id,
            model="qwen3.5-flash",
            prompt_version="v1",
            summary="First summary.",
            citations=[
                Citation(article_id=articles[0].id, excerpt="Body 1."),
                Citation(article_id=articles[1].id, excerpt="Body 2."),
                Citation(article_id=articles[2].id, excerpt="Body 3."),
            ],
        ),
        BatchSummary(
            batch_id=batch.id,
            model="qwen3.5-flash",
            prompt_version="v2",
            summary="Second summary.",
            citations=[
                Citation(article_id=articles[0].id, excerpt="Body 1."),
                Citation(article_id=articles[1].id, excerpt="Body 2."),
                Citation(article_id=articles[2].id, excerpt="Body 3."),
            ],
        ),
    ]

    async with session_scope(migrated) as sess:
        await upsert_source(sess, source)
        for article in articles:
            await save_article(sess, article)
        await save_article_batch(sess, batch)
        for summary in summaries:
            await save_batch_summary(sess, summary)
        found = await get_batch_summaries_by_ids(sess, [summaries[1].id, summaries[0].id])
        empty = await get_batch_summaries_by_ids(sess, [])

    assert {summary.id for summary in found} == {summaries[0].id, summaries[1].id}
    assert empty == []
