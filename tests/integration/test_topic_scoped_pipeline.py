"""Headline T6 behaviour: per-topic briefs and topic-scoped feed polling (spec §4 / §4.1)."""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from alembic import command
from analyst_engine.config import Settings
from analyst_engine.domain.models import (
    Article,
    Cadence,
    Citation,
    Source,
    SourceFeed,
    Topic,
)
from analyst_engine.ingestion.models import IngestionResult
from analyst_engine.models.gateway import ModelGateway, ModelTask, ModelUsage
from analyst_engine.persistence.engine import get_async_engine, get_session_factory, session_scope
from analyst_engine.persistence.repositories import (
    create_topic,
    get_article_by_fingerprint,
    get_brief_by_cadence_interval,
    get_source_by_stable_id,
    get_source_feed_by_fingerprint,
    list_due_source_feeds,
    save_article,
    upsert_source,
    upsert_source_feed,
)
from analyst_engine.pipeline.daily_brief import DailyBriefPipeline
from analyst_engine.summarization.prompts import BatchSummaryModelResult
from analyst_engine.workflows.graphs import FrontierResult
from analyst_engine.workflows.runner import WorkflowRunner

try:
    from fixtures import (  # type: ignore[import-not-found]
        docker_endpoint_available,
        ensure_topic,
        truncate_domain_tables,
    )
except ImportError:  # pragma: no cover
    from tests.fixtures import (
        docker_endpoint_available,
        truncate_domain_tables,
    )

try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    PostgresContainer = None  # type: ignore[import-untyped, unused-ignore]


pytestmark = pytest.mark.integration

_TARGET_DATE = date(2026, 7, 13)
_SHARED_EXCERPT = "Market participants reassessed risk after the policy announcement."
_FIXED_NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
_ARTICLE_ID_RE = re.compile(
    r"--- ARTICLE id=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}) ---"
)


@pytest.fixture(scope="session")
def pg_container():  # type: ignore[no-untyped-def, unused-ignore]
    if os.environ.get("DATABASE_URL"):
        yield None
        return
    if PostgresContainer is None:
        pytest.skip("integration database unavailable: no DATABASE_URL or testcontainers")
    if not docker_endpoint_available():
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
        batch_summary_model="qwen3.5-flash",
        batch_summary_prompt_version="v1",
        title_similarity_threshold=0.35,
        grouping_algorithm_version="v1",
        allowed_languages=["en"],
        max_articles_per_run=50,
        max_feeds_per_run=50,
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


class _CountingGateway(ModelGateway):
    def __init__(self) -> None:
        self.call_count = 0

    async def generate(
        self,
        *,
        task: ModelTask,
        messages: list[dict[str, str]],
        output_schema: type[BaseModel],
        correlation_id: str,
    ) -> tuple[BaseModel, ModelUsage]:
        self.call_count += 1
        if task is ModelTask.BATCH_SUMMARY:
            content = messages[-1]["content"]
            article_ids = _ARTICLE_ID_RE.findall(content)
            if not article_ids:
                raise AssertionError("expected article ids in batch summary prompt")
            return (
                BatchSummaryModelResult(
                    summary=f"Summary for {correlation_id}",
                    source_notes="notes",
                    entities=["entity"],
                    topics=["topic"],
                    citations=[Citation(article_id=UUID(article_ids[0]), excerpt=_SHARED_EXCERPT)],
                ),
                ModelUsage(model="fake-batch", prompt_tokens=1, completion_tokens=1),
            )
        return (
            FrontierResult(
                brief_content=f"Brief for {correlation_id}",
                narrative_state={"themes": ["test"]},
                change_log=["init"],
                expectations=[],
            ),
            ModelUsage(model="fake-frontier", prompt_tokens=1, completion_tokens=1),
        )

    def get_model_for_task(self, task: ModelTask) -> str:
        return "fake-model"

    async def embed(self, *, text: str, correlation_id: str) -> tuple[list[float], ModelUsage]:
        return [0.1] * 1536, ModelUsage(model="fake-embed")


class _NoOpIngestionService:
    async def poll_feed(self, _feed: object) -> list[IngestionResult]:
        return []


class _RecordingIngestionService:
    """Records which feeds were polled and stamps last_polled_at like a real poll."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], now: datetime) -> None:
        self.session_factory = session_factory
        self.now = now
        self.polled_feed_ids: list[UUID] = []

    async def poll_feed(self, feed: SourceFeed) -> list[IngestionResult]:
        self.polled_feed_ids.append(feed.id)
        updated = feed.model_copy(update={"last_polled_at": self.now})
        async with session_scope(self.session_factory) as session:
            await upsert_source_feed(session, updated)
        return []


def _pipeline(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    gateway: ModelGateway,
    ingestion_service: object | None = None,
) -> DailyBriefPipeline:
    @asynccontextmanager
    async def checkpointer_factory() -> AsyncIterator[MemorySaver]:
        yield MemorySaver()

    runner = WorkflowRunner(settings, gateway, session_factory, checkpointer_factory)
    return DailyBriefPipeline(
        session_factory=session_factory,
        ingestion_service=ingestion_service or _NoOpIngestionService(),  # type: ignore[arg-type]
        runner=runner,
        gateway=gateway,
        settings=settings,
        clock=lambda: _FIXED_NOW,
    )


async def _seed_topic_with_articles(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    topic: Topic,
    stable_id: str,
    title_prefix: str,
) -> tuple[Topic, Source, list[Article]]:
    source = Source(
        topic_id=topic.id,
        stable_id=stable_id,
        name=f"{title_prefix} Source",
        normalized_domain=f"{stable_id}.example.com",
    )
    published_at = datetime.combine(_TARGET_DATE, datetime.min.time(), tzinfo=UTC)
    articles = [
        Article(
            topic_id=topic.id,
            source_id=source.id,
            url=f"https://{stable_id}.example.com/{index}",
            url_fingerprint=f"fp-{stable_id}-{index}",
            title=f"{title_prefix} Story {index}",
            published_at=published_at,
            language="en",
            cleaned_content=_SHARED_EXCERPT,
        )
        for index in range(1, 4)
    ]
    async with session_scope(session_factory) as session:
        await create_topic(session, topic)
        await ensure_topic(session)
        await upsert_source(session, source)
        for article in articles:
            await save_article(session, article)
    return topic, source, articles


@pytest.mark.asyncio
async def test_two_topics_produce_independent_briefs_for_same_date(
    migrated: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    """Headline slice behaviour (spec §4 / success criterion): two topics → two briefs."""
    topic_a = Topic(
        id=uuid4(),
        name="Topic A",
        description="First topic",
        keywords=["alpha", "topic-a"],
    )
    topic_b = Topic(
        id=uuid4(),
        name="Topic B",
        description="Second topic",
        keywords=["beta", "topic-b"],
    )
    _topic_a, _src_a, articles_a = await _seed_topic_with_articles(
        migrated, topic=topic_a, stable_id="topic-a", title_prefix="Alpha"
    )
    _topic_b, _src_b, articles_b = await _seed_topic_with_articles(
        migrated, topic=topic_b, stable_id="topic-b", title_prefix="Beta"
    )

    gateway = _CountingGateway()
    pipeline = _pipeline(settings=test_settings, session_factory=migrated, gateway=gateway)

    result_a = await pipeline.run(_TARGET_DATE, topic_id=topic_a.id)
    result_b = await pipeline.run(_TARGET_DATE, topic_id=topic_b.id)

    assert result_a.is_no_content is False
    assert result_b.is_no_content is False
    assert result_a.brief_id is not None
    assert result_b.brief_id is not None
    assert result_a.brief_id != result_b.brief_id
    assert result_a.workflow_run_id != result_b.workflow_run_id

    async with session_scope(migrated) as session:
        brief_a = await get_brief_by_cadence_interval(
            session, Cadence.DAILY, _TARGET_DATE, _TARGET_DATE, topic_id=topic_a.id
        )
        brief_b = await get_brief_by_cadence_interval(
            session, Cadence.DAILY, _TARGET_DATE, _TARGET_DATE, topic_id=topic_b.id
        )
        assert brief_a is not None and brief_b is not None
        assert brief_a.topic_id == topic_a.id
        assert brief_b.topic_id == topic_b.id
        # Each brief cites only its own topic's articles.
        ids_a = {article.id for article in articles_a}
        ids_b = {article.id for article in articles_b}
        assert set(brief_a.cited_article_ids).issubset(ids_a)
        assert set(brief_b.cited_article_ids).issubset(ids_b)
        assert set(brief_a.cited_article_ids).isdisjoint(ids_b)
        assert set(brief_b.cited_article_ids).isdisjoint(ids_a)


@pytest.mark.asyncio
async def test_topic_run_does_not_consume_other_topic_feed_due_status(
    migrated: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    """Spec §4.1 regression: topic A must not poll topic B's due feeds.

    If poll were global, running A first would stamp B's last_polled_at and
    B's later run would find its feeds not due — ordering would starve B.
    """
    topic_a = Topic(
        id=uuid4(),
        name="Poll Topic A",
        description="A",
        keywords=["poll-a"],
    )
    topic_b = Topic(
        id=uuid4(),
        name="Poll Topic B",
        description="B",
        keywords=["poll-b"],
    )
    source_a = Source(
        topic_id=topic_a.id,
        stable_id="poll-src-a",
        name="A Source",
        normalized_domain="a.example.com",
    )
    source_b = Source(
        topic_id=topic_b.id,
        stable_id="poll-src-b",
        name="B Source",
        normalized_domain="b.example.com",
    )
    feed_a = SourceFeed(
        source_id=source_a.id,
        feed_url="https://a.example.com/feed.xml",
        feed_url_fingerprint="feed-fp-topic-a",
        enabled=True,
        poll_interval_minutes=60,
    )
    feed_b = SourceFeed(
        source_id=source_b.id,
        feed_url="https://b.example.com/feed.xml",
        feed_url_fingerprint="feed-fp-topic-b",
        enabled=True,
        poll_interval_minutes=60,
    )

    async with session_scope(migrated) as session:
        await create_topic(session, topic_a)
        await create_topic(session, topic_b)
        await upsert_source(session, source_a)
        await upsert_source(session, source_b)
        await upsert_source_feed(session, feed_a)
        await upsert_source_feed(session, feed_b)

        # Both feeds are due before any run.
        due_a = await list_due_source_feeds(session, _FIXED_NOW, topic_id=topic_a.id)
        due_b = await list_due_source_feeds(session, _FIXED_NOW, topic_id=topic_b.id)
        assert [f.feed_url_fingerprint for f in due_a] == ["feed-fp-topic-a"]
        assert [f.feed_url_fingerprint for f in due_b] == ["feed-fp-topic-b"]

    recorder = _RecordingIngestionService(migrated, _FIXED_NOW)
    pipeline = _pipeline(
        settings=test_settings,
        session_factory=migrated,
        gateway=_CountingGateway(),
        ingestion_service=recorder,
    )

    # Run topic A first — the ordering that would starve B if poll were global.
    await pipeline.run(_TARGET_DATE, topic_id=topic_a.id)

    assert recorder.polled_feed_ids == [feed_a.id]

    async with session_scope(migrated) as session:
        persisted_a = await get_source_feed_by_fingerprint(
            session, "feed-fp-topic-a", source_id=source_a.id
        )
        persisted_b = await get_source_feed_by_fingerprint(
            session, "feed-fp-topic-b", source_id=source_b.id
        )
        assert persisted_a is not None and persisted_b is not None
        assert persisted_a.last_polled_at == _FIXED_NOW
        # B's feed must still be due — A must not have stamped it.
        assert persisted_b.last_polled_at is None
        due_b_after_a = await list_due_source_feeds(session, _FIXED_NOW, topic_id=topic_b.id)
        assert [f.feed_url_fingerprint for f in due_b_after_a] == ["feed-fp-topic-b"]

    # Topic B still polls and consumes its own feed.
    await pipeline.run(_TARGET_DATE, topic_id=topic_b.id)
    assert recorder.polled_feed_ids == [feed_a.id, feed_b.id]

    async with session_scope(migrated) as session:
        persisted_b = await get_source_feed_by_fingerprint(
            session, "feed-fp-topic-b", source_id=source_b.id
        )
        assert persisted_b is not None
        assert persisted_b.last_polled_at == _FIXED_NOW
        # After B runs, B's feed is no longer due within the interval.
        not_yet = _FIXED_NOW + timedelta(minutes=30)
        due_b_later = await list_due_source_feeds(session, not_yet, topic_id=topic_b.id)
        assert due_b_later == []


@pytest.mark.asyncio
async def test_same_stable_id_and_url_fingerprint_allowed_across_topics(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    """Discriminating acceptance: identical identifiers under two topics (spec §6).

    Reuses the *same* stable_id and url_fingerprint across topics — a test with
    distinct per-topic identifiers would pass both before and after the fix.
    """
    shared_stable_id = "shared-source-stable-id"
    shared_fingerprint = "shared-url-fingerprint"

    topic_a = Topic(
        id=uuid4(),
        name="Share Topic A",
        description="A",
        keywords=["share-a"],
    )
    topic_b = Topic(
        id=uuid4(),
        name="Share Topic B",
        description="B",
        keywords=["share-b"],
    )
    source_a = Source(
        topic_id=topic_a.id,
        stable_id=shared_stable_id,
        name="Shared Source A",
        normalized_domain="shared.example.com",
    )
    source_b = Source(
        topic_id=topic_b.id,
        stable_id=shared_stable_id,
        name="Shared Source B",
        normalized_domain="shared.example.com",
    )
    published_at = datetime.combine(_TARGET_DATE, datetime.min.time(), tzinfo=UTC)
    article_a = Article(
        topic_id=topic_a.id,
        source_id=source_a.id,
        url="https://shared.example.com/story",
        url_fingerprint=shared_fingerprint,
        title="Shared Story A",
        published_at=published_at,
        language="en",
        cleaned_content=_SHARED_EXCERPT,
    )
    article_b = Article(
        topic_id=topic_b.id,
        source_id=source_b.id,
        url="https://shared.example.com/story",
        url_fingerprint=shared_fingerprint,
        title="Shared Story B",
        published_at=published_at,
        language="en",
        cleaned_content=_SHARED_EXCERPT,
    )

    async with session_scope(migrated) as session:
        await create_topic(session, topic_a)
        await create_topic(session, topic_b)
        await upsert_source(session, source_a)
        await upsert_source(session, source_b)
        await save_article(session, article_a)
        await save_article(session, article_b)

        got_a = await get_source_by_stable_id(session, shared_stable_id, topic_id=topic_a.id)
        got_b = await get_source_by_stable_id(session, shared_stable_id, topic_id=topic_b.id)
        assert got_a is not None and got_b is not None
        assert got_a.id == source_a.id
        assert got_b.id == source_b.id
        assert got_a.id != got_b.id
        assert got_a.topic_id == topic_a.id
        assert got_b.topic_id == topic_b.id

        art_a = await get_article_by_fingerprint(session, shared_fingerprint, topic_id=topic_a.id)
        art_b = await get_article_by_fingerprint(session, shared_fingerprint, topic_id=topic_b.id)
        assert art_a is not None and art_b is not None
        assert art_a.id == article_a.id
        assert art_b.id == article_b.id
        assert art_a.id != art_b.id
        assert art_a.topic_id == topic_a.id
        assert art_b.topic_id == topic_b.id
