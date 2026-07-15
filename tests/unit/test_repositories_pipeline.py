"""Repository integration tests for pipeline bulk lookups and citation checks."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta

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
    list_eligible_batch_summaries_for_window,
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
    await truncate_domain_tables(session_factory)
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


@pytest.mark.asyncio
async def test_list_eligible_batch_summaries_for_window_respects_exact_boundary(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    source = Source(
        stable_id="pipeline-src-window",
        name="Window Source",
        normalized_domain="example.com",
    )
    window_start = date(2026, 7, 6)
    window_end = date(2026, 7, 12)

    def _batch_and_summary(
        published_at: datetime, *, key: str
    ) -> tuple[ArticleBatch, BatchSummary, list[Article]]:
        # ArticleBatch requires 3-5 article_ids; all three share the same
        # published_at here since the boundary under test is which instant
        # the batch's articles fall on, not batch composition.
        articles = [
            Article(
                source_id=source.id,
                url=f"https://example.com/{key}-{index}",
                url_fingerprint=f"fp-{key}-{index}",
                title=f"Window Article {key} {index}",
                published_at=published_at,
                cleaned_content=f"Body {key} {index}.",
            )
            for index in range(1, 4)
        ]
        batch = ArticleBatch(
            article_ids=[article.id for article in articles],
            batch_key=f"batch:window-{key}",
            grouping_method=GroupingMethod.TITLE_TOKEN_JACCARD,
            embedding_model="test-emb",
        )
        summary = BatchSummary(
            batch_id=batch.id,
            model="qwen3.5-flash",
            prompt_version="v1",
            summary=f"Summary {key}.",
            citations=[Citation(article_id=articles[0].id, excerpt=articles[0].cleaned_content)],
        )
        return batch, summary, articles

    in_lower_boundary = _batch_and_summary(
        datetime.combine(window_start, datetime.min.time(), tzinfo=UTC), key="lower"
    )
    in_upper_boundary = _batch_and_summary(
        datetime(2026, 7, 12, 23, 59, 59, tzinfo=UTC), key="upper"
    )
    before_window = _batch_and_summary(datetime(2026, 7, 5, 23, 59, 59, tzinfo=UTC), key="before")
    after_window = _batch_and_summary(
        datetime.combine(window_end + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
        key="after",
    )

    async with session_scope(migrated) as sess:
        await upsert_source(sess, source)
        for batch, summary, articles in (
            in_lower_boundary,
            in_upper_boundary,
            before_window,
            after_window,
        ):
            for article in articles:
                await save_article(sess, article)
            await save_article_batch(sess, batch)
            await save_batch_summary(sess, summary)

        eligible = await list_eligible_batch_summaries_for_window(sess, window_start, window_end)

    eligible_ids = {summary.id for summary in eligible}
    assert eligible_ids == {in_lower_boundary[1].id, in_upper_boundary[1].id}


@pytest.mark.asyncio
async def test_list_eligible_batch_summaries_for_window_includes_batch_with_mixed_dates(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    source = Source(
        stable_id="pipeline-src-window-mixed",
        name="Window Mixed Source",
        normalized_domain="example.com",
    )
    window_start = date(2026, 7, 6)
    window_end = date(2026, 7, 12)
    in_window_article = Article(
        source_id=source.id,
        url="https://example.com/mixed-in",
        url_fingerprint="fp-mixed-in",
        title="Mixed In Window",
        published_at=datetime(2026, 7, 8, 12, 0, tzinfo=UTC),
        cleaned_content="In window body.",
    )
    out_of_window_article = Article(
        source_id=source.id,
        url="https://example.com/mixed-out",
        url_fingerprint="fp-mixed-out",
        title="Mixed Out Of Window",
        published_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        cleaned_content="Out of window body.",
    )
    second_out_of_window_article = Article(
        source_id=source.id,
        url="https://example.com/mixed-out-2",
        url_fingerprint="fp-mixed-out-2",
        title="Mixed Out Of Window Two",
        published_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        cleaned_content="Second out of window body.",
    )
    batch = ArticleBatch(
        article_ids=[
            in_window_article.id,
            out_of_window_article.id,
            second_out_of_window_article.id,
        ],
        batch_key="batch:window-mixed",
        grouping_method=GroupingMethod.TITLE_TOKEN_JACCARD,
        embedding_model="test-emb",
    )
    summary = BatchSummary(
        batch_id=batch.id,
        model="qwen3.5-flash",
        prompt_version="v1",
        summary="Mixed batch summary.",
        citations=[Citation(article_id=in_window_article.id, excerpt="In window body.")],
    )

    async with session_scope(migrated) as sess:
        await upsert_source(sess, source)
        await save_article(sess, in_window_article)
        await save_article(sess, out_of_window_article)
        await save_article(sess, second_out_of_window_article)
        await save_article_batch(sess, batch)
        await save_batch_summary(sess, summary)

        eligible = await list_eligible_batch_summaries_for_window(sess, window_start, window_end)

    assert {s.id for s in eligible} == {summary.id}


@pytest.mark.asyncio
async def test_list_eligible_batch_summaries_for_window_empty_window_returns_nothing(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    source = Source(
        stable_id="pipeline-src-window-empty",
        name="Window Empty Source",
        normalized_domain="example.com",
    )
    article = Article(
        source_id=source.id,
        url="https://example.com/no-summary",
        url_fingerprint="fp-no-summary",
        title="No Summary Article",
        published_at=datetime(2026, 7, 8, 12, 0, tzinfo=UTC),
        cleaned_content="Body.",
    )

    async with session_scope(migrated) as sess:
        await upsert_source(sess, source)
        await save_article(sess, article)

        eligible = await list_eligible_batch_summaries_for_window(
            sess, date(2026, 7, 6), date(2026, 7, 12)
        )

    assert eligible == []
