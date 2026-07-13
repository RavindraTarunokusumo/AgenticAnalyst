"""RSS repository integration tests using Testcontainers.

Exercises Task 3 repository functions against a real PostgreSQL database.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta

import pytest
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from alembic import command
from analyst_engine.config import Settings
from analyst_engine.domain.models import (
    Article,
    ArticleBatch,
    BatchSummary,
    Citation,
    GroupingMethod,
    Source,
    SourceFeed,
)
from analyst_engine.persistence.engine import get_async_engine, get_session_factory, session_scope
from analyst_engine.persistence.repositories import (
    get_batch_summary_by_identity,
    list_due_source_feeds,
    list_eligible_unbatched_articles,
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
    return session_factory


@pytest.mark.asyncio
async def test_upsert_source_feed_is_idempotent_by_fingerprint(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    source = Source(
        stable_id="rss-src-upsert",
        name="RSS Source",
        normalized_domain="example.com",
    )
    first = SourceFeed(
        source_id=source.id,
        feed_url="https://example.com/feed.xml",
        feed_url_fingerprint="feed-fp-upsert",
        enabled=True,
        poll_interval_minutes=60,
        etag="etag-1",
    )
    second = SourceFeed(
        source_id=source.id,
        feed_url="https://example.com/feed.xml",
        feed_url_fingerprint="feed-fp-upsert",
        enabled=False,
        poll_interval_minutes=30,
        etag="etag-2",
        last_error_summary="poll failed",
        updated_at=datetime(2026, 7, 13, 12, 0, tzinfo=UTC),
    )

    async with session_scope(migrated) as sess:
        await upsert_source(sess, source)
        persisted_first = await upsert_source_feed(sess, first)
        persisted_second = await upsert_source_feed(sess, second)

    assert persisted_first.id == persisted_second.id
    assert persisted_second.enabled is False
    assert persisted_second.poll_interval_minutes == 30
    assert persisted_second.etag == "etag-2"
    assert persisted_second.last_error_summary == "poll failed"


@pytest.mark.asyncio
async def test_list_due_source_feeds_orders_nulls_first_and_filters_disabled(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    source = Source(
        stable_id="rss-src-due",
        name="Due Feeds Source",
        normalized_domain="example.com",
    )
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    never_polled = SourceFeed(
        source_id=source.id,
        feed_url="https://example.com/never.xml",
        feed_url_fingerprint="feed-fp-never",
        enabled=True,
        poll_interval_minutes=60,
    )
    overdue = SourceFeed(
        source_id=source.id,
        feed_url="https://example.com/overdue.xml",
        feed_url_fingerprint="feed-fp-overdue",
        enabled=True,
        poll_interval_minutes=60,
        last_polled_at=now - timedelta(minutes=120),
    )
    not_due = SourceFeed(
        source_id=source.id,
        feed_url="https://example.com/recent.xml",
        feed_url_fingerprint="feed-fp-recent",
        enabled=True,
        poll_interval_minutes=60,
        last_polled_at=now - timedelta(minutes=30),
    )
    disabled = SourceFeed(
        source_id=source.id,
        feed_url="https://example.com/disabled.xml",
        feed_url_fingerprint="feed-fp-disabled",
        enabled=False,
        poll_interval_minutes=60,
    )

    async with session_scope(migrated) as sess:
        await upsert_source(sess, source)
        await upsert_source_feed(sess, never_polled)
        await upsert_source_feed(sess, overdue)
        await upsert_source_feed(sess, not_due)
        await upsert_source_feed(sess, disabled)
        due = await list_due_source_feeds(sess, now)

    assert [feed.feed_url_fingerprint for feed in due] == [
        "feed-fp-never",
        "feed-fp-overdue",
    ]


@pytest.mark.asyncio
async def test_list_eligible_unbatched_articles_excludes_batched_articles(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    source = Source(
        stable_id="rss-src-unbatched",
        name="Unbatched Source",
        normalized_domain="example.com",
    )
    target_date = date(2026, 7, 13)
    day_start = datetime(2026, 7, 13, 8, 0, tzinfo=UTC)
    day_end = datetime(2026, 7, 13, 20, 0, tzinfo=UTC)
    after_cutoff = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)
    articles = [
        Article(
            source_id=source.id,
            url="https://example.com/a1",
            url_fingerprint="fp-a1",
            title="Article One",
            published_at=day_start,
            language="en",
            cleaned_content="Body one.",
        ),
        Article(
            source_id=source.id,
            url="https://example.com/a2",
            url_fingerprint="fp-a2",
            title="Article Two",
            published_at=day_end,
            language="en",
            cleaned_content="Body two.",
        ),
        Article(
            source_id=source.id,
            url="https://example.com/a3",
            url_fingerprint="fp-a3",
            title="Article Three",
            published_at=day_end,
            language="en",
            cleaned_content="Body three.",
        ),
        Article(
            source_id=source.id,
            url="https://example.com/a4",
            url_fingerprint="fp-a4",
            title="Article Four",
            published_at=day_end,
            language="en",
            cleaned_content="Body four.",
        ),
        Article(
            source_id=source.id,
            url="https://example.com/fr",
            url_fingerprint="fp-fr",
            title="Article French",
            published_at=day_end,
            language="fr",
            cleaned_content="Corps.",
        ),
        Article(
            source_id=source.id,
            url="https://example.com/late",
            url_fingerprint="fp-late",
            title="Article Late",
            published_at=after_cutoff,
            language="en",
            cleaned_content="Too late.",
        ),
    ]
    batch = ArticleBatch(
        article_ids=[articles[0].id, articles[1].id, articles[2].id],
        batch_key="batch:fp-a1,fp-a2,fp-a3",
        grouping_method=GroupingMethod.TITLE_TOKEN_JACCARD,
        embedding_model="test-emb",
    )

    async with session_scope(migrated) as sess:
        await upsert_source(sess, source)
        for article in articles:
            await save_article(sess, article)
        await save_article_batch(sess, batch)
        eligible = await list_eligible_unbatched_articles(sess, target_date, ["en"])

    assert [article.url_fingerprint for article in eligible] == ["fp-a4"]


@pytest.mark.asyncio
async def test_get_batch_summary_by_identity_returns_match_or_none(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    source = Source(
        stable_id="rss-src-summary",
        name="Summary Source",
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
        batch_key="batch:summary-test",
        grouping_method=GroupingMethod.TITLE_TOKEN_JACCARD,
        embedding_model="test-emb",
    )
    summary = BatchSummary(
        batch_id=batch.id,
        model="qwen3.5-flash",
        prompt_version="v1",
        summary="Batch summary text.",
        citations=[
            Citation(article_id=articles[0].id, excerpt="Body 1."),
            Citation(article_id=articles[1].id, excerpt="Body 2."),
            Citation(article_id=articles[2].id, excerpt="Body 3."),
        ],
    )

    async with session_scope(migrated) as sess:
        await upsert_source(sess, source)
        for article in articles:
            await save_article(sess, article)
        await save_article_batch(sess, batch)
        await save_batch_summary(sess, summary)
        found = await get_batch_summary_by_identity(sess, batch.id, "qwen3.5-flash", "v1")
        missing = await get_batch_summary_by_identity(sess, batch.id, "qwen3.5-flash", "v2")

    assert found is not None
    assert found.id == summary.id
    assert missing is None
