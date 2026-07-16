"""End-to-end integration test for DailyBriefPipeline."""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from alembic.config import Config
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from alembic import command
from analyst_engine.config import Settings
from analyst_engine.domain.models import Article, Cadence, Citation, Source
from analyst_engine.ingestion.models import IngestionResult
from analyst_engine.models.gateway import ModelGateway, ModelTask, ModelUsage
from analyst_engine.persistence.engine import get_async_engine, get_session_factory, session_scope
from analyst_engine.persistence.models import NarrativeStateVersion as ORMNarrative
from analyst_engine.persistence.repositories import (
    get_brief_by_cadence_interval,
    save_article,
    upsert_source,
)
from analyst_engine.pipeline.daily_brief import DailyBriefPipeline
from analyst_engine.summarization.prompts import BatchSummaryModelResult
from analyst_engine.workflows.graphs import FrontierResult
from analyst_engine.workflows.runner import WorkflowRunner

try:
    from fixtures import (  # type: ignore[import-not-found]
        DEFAULT_TOPIC_ID,
        docker_endpoint_available,
        ensure_topic,
        truncate_domain_tables,
    )
except ImportError:  # pragma: no cover
    from tests.fixtures import (
        DEFAULT_TOPIC_ID,
        docker_endpoint_available,
        ensure_topic,
        truncate_domain_tables,
    )

try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    PostgresContainer = None  # type: ignore[import-untyped, unused-ignore]


pytestmark = pytest.mark.integration

_TARGET_DATE = date(2026, 7, 13)
_SHARED_EXCERPT = "Integration article body for daily pipeline."
_ARTICLE_ID_RE = re.compile(
    r"--- ARTICLE id=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}) ---"
)


class _NoOpIngestionService:
    async def poll_feed(self, _feed: object) -> list[IngestionResult]:
        return []


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
                    summary="Integration batch summary.",
                    citations=[
                        Citation(
                            article_id=UUID(article_ids[0]),
                            excerpt=_SHARED_EXCERPT,
                        )
                    ],
                ),
                ModelUsage(model="fake-batch"),
            )
        return (
            FrontierResult(
                brief_content=f"Integration brief for {correlation_id}",
                narrative_state={"themes": ["integration"]},
                change_log=["created"],
            ),
            ModelUsage(model="fake-frontier"),
        )

    def get_model_for_task(self, task: ModelTask) -> str:
        return "fake-model"

    async def embed(self, *, text: str, correlation_id: str) -> tuple[list[float], ModelUsage]:
        return [0.1] * 1536, ModelUsage(model="fake-embed")


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
        dashscope_api_key="test-key-for-pipeline",
        database_url=test_database_url,  # type: ignore[arg-type, unused-ignore]
        batch_summary_model="qwen3.5-flash",
        batch_summary_prompt_version="v1",
        title_similarity_threshold=0.35,
        grouping_algorithm_version="v1",
        allowed_languages=["en"],
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


def _pipeline(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    gateway: _CountingGateway,
) -> DailyBriefPipeline:
    @asynccontextmanager
    async def checkpointer_factory() -> AsyncIterator[MemorySaver]:
        yield MemorySaver()

    runner = WorkflowRunner(settings, gateway, session_factory, checkpointer_factory)
    return DailyBriefPipeline(
        session_factory=session_factory,
        ingestion_service=_NoOpIngestionService(),  # type: ignore[arg-type]
        runner=runner,
        gateway=gateway,
        settings=settings,
        clock=lambda: datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    )


async def _seed_eligible_articles(
    session_factory: async_sessionmaker[AsyncSession],
) -> Source:
    source = Source(
        topic_id=DEFAULT_TOPIC_ID,
        stable_id="pipeline-integration-src",
        name="Integration Source",
        normalized_domain="example.com",
    )
    published_at = datetime.combine(_TARGET_DATE, datetime.min.time(), tzinfo=UTC)
    articles = [
        Article(
            topic_id=DEFAULT_TOPIC_ID,
            source_id=source.id,
            url=f"https://example.com/integration-{index}",
            url_fingerprint=f"fp-integration-{index}",
            title=f"Daily Market Update {index}",
            published_at=published_at,
            language="en",
            cleaned_content=_SHARED_EXCERPT,
        )
        for index in range(1, 4)
    ]
    async with session_scope(session_factory) as sess:
        await ensure_topic(sess)
        await upsert_source(sess, source)
        for article in articles:
            await save_article(sess, article)
    return source


@pytest.mark.asyncio
async def test_daily_pipeline_persists_brief_and_is_idempotent_on_rerun(
    migrated: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    await _seed_eligible_articles(migrated)
    gateway = _CountingGateway()
    pipeline = _pipeline(
        settings=test_settings,
        session_factory=migrated,
        gateway=gateway,
    )

    first = await pipeline.run(_TARGET_DATE, topic_id=DEFAULT_TOPIC_ID)

    assert first.is_no_content is False
    assert first.workflow_run_id is not None
    assert first.brief_id is not None
    assert gateway.call_count == 2

    async with session_scope(migrated) as sess:
        brief = await get_brief_by_cadence_interval(
            sess, Cadence.DAILY, _TARGET_DATE, _TARGET_DATE, topic_id=DEFAULT_TOPIC_ID
        )
        assert brief is not None
        assert brief.id == first.brief_id
        assert brief.narrative_state_version_id is not None
        narrative = (
            await sess.execute(
                select(ORMNarrative).where(ORMNarrative.id == brief.narrative_state_version_id)
            )
        ).scalar_one_or_none()
        assert narrative is not None

    second = await pipeline.run(_TARGET_DATE, topic_id=DEFAULT_TOPIC_ID)

    assert second.workflow_run_id == first.workflow_run_id
    assert second.brief_id == first.brief_id
    assert gateway.call_count == 2
