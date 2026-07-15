"""End-to-end integration tests for PeriodicBriefPipeline (weekly/monthly)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime

import pytest
from alembic.config import Config
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel
from sqlalchemy import select
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
from analyst_engine.models.gateway import ModelGateway, ModelTask, ModelUsage
from analyst_engine.persistence.engine import get_async_engine, get_session_factory, session_scope
from analyst_engine.persistence.models import NarrativeStateVersion as ORMNarrative
from analyst_engine.persistence.repositories import (
    get_brief_by_cadence_interval,
    save_article,
    save_article_batch,
    save_batch_summary,
    save_brief,
    upsert_source,
)
from analyst_engine.pipeline.periodic_brief import PeriodicBriefPipeline
from analyst_engine.workflows.graphs import FrontierResult
from analyst_engine.workflows.runner import WorkflowRunner

try:
    from fixtures import (  # type: ignore[import-not-found]
        docker_endpoint_available,
        truncate_domain_tables,
    )
except ImportError:  # pragma: no cover
    from tests.fixtures import docker_endpoint_available, truncate_domain_tables

try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    PostgresContainer = None  # type: ignore[import-untyped, unused-ignore]


pytestmark = pytest.mark.integration

_SHARED_EXCERPT = "Integration article body for periodic pipeline."


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
        dashscope_api_key="test-key-for-periodic-pipeline",
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


def _pipeline(
    *,
    cadence: Cadence,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    gateway: _CountingGateway,
    clock: datetime,
) -> PeriodicBriefPipeline:
    @asynccontextmanager
    async def checkpointer_factory() -> AsyncIterator[MemorySaver]:
        yield MemorySaver()

    runner = WorkflowRunner(settings, gateway, session_factory, checkpointer_factory)
    return PeriodicBriefPipeline(
        cadence=cadence,
        session_factory=session_factory,
        runner=runner,
        clock=lambda: clock,
    )


async def _seed_batch_summary(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source: Source,
    published_at: datetime,
    key: str,
) -> BatchSummary:
    # ArticleBatch requires 3-5 article_ids; all three share the same
    # published_at since only the batch's window membership is under test.
    articles = [
        Article(
            source_id=source.id,
            url=f"https://example.com/periodic-{key}-{index}",
            url_fingerprint=f"fp-periodic-{key}-{index}",
            title=f"Periodic Update {key} {index}",
            published_at=published_at,
            language="en",
            cleaned_content=_SHARED_EXCERPT,
        )
        for index in range(1, 4)
    ]
    batch = ArticleBatch(
        article_ids=[article.id for article in articles],
        batch_key=f"batch:periodic-{key}",
        grouping_method=GroupingMethod.TITLE_TOKEN_JACCARD,
        embedding_model="test-emb",
    )
    summary = BatchSummary(
        batch_id=batch.id,
        model="qwen3.5-flash",
        prompt_version="v1",
        summary=f"Periodic summary {key}.",
        citations=[Citation(article_id=articles[0].id, excerpt=_SHARED_EXCERPT)],
    )
    async with session_scope(session_factory) as sess:
        for article in articles:
            await save_article(sess, article)
        await save_article_batch(sess, batch)
        await save_batch_summary(sess, summary)
    return summary


@pytest.mark.asyncio
async def test_weekly_pipeline_persists_brief_and_is_idempotent_on_rerun(
    migrated: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    source = Source(
        stable_id="periodic-integration-src-weekly",
        name="Periodic Integration Source",
        normalized_domain="example.com",
    )
    async with session_scope(migrated) as sess:
        await upsert_source(sess, source)

    week_start = date(2026, 7, 6)
    for offset, key in ((0, "mon"), (2, "wed"), (5, "sat")):
        await _seed_batch_summary(
            migrated,
            source=source,
            published_at=datetime.combine(
                date(2026, 7, 6 + offset), datetime.min.time(), tzinfo=UTC
            ),
            key=key,
        )

    gateway = _CountingGateway()
    pipeline = _pipeline(
        cadence=Cadence.WEEKLY,
        settings=test_settings,
        session_factory=migrated,
        gateway=gateway,
        clock=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
    )

    first = await pipeline.run()

    assert first.covered_start == week_start
    assert first.covered_end == date(2026, 7, 12)
    assert first.is_no_content is False
    assert first.summaries_selected == 3
    assert first.brief_id is not None
    assert gateway.call_count == 1

    async with session_scope(migrated) as sess:
        brief = await get_brief_by_cadence_interval(
            sess, Cadence.WEEKLY, week_start, date(2026, 7, 12)
        )
        assert brief is not None
        assert brief.id == first.brief_id
        assert len(brief.cited_batch_summary_ids) == 3
        assert brief.narrative_state_version_id is not None
        narrative = (
            await sess.execute(
                select(ORMNarrative).where(ORMNarrative.id == brief.narrative_state_version_id)
            )
        ).scalar_one_or_none()
        assert narrative is not None

    second = await pipeline.run()

    assert second.workflow_run_id == first.workflow_run_id
    assert second.brief_id == first.brief_id
    assert gateway.call_count == 1


@pytest.mark.asyncio
async def test_monthly_pipeline_persists_brief_from_activity_across_weeks(
    migrated: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    source = Source(
        stable_id="periodic-integration-src-monthly",
        name="Periodic Integration Source Monthly",
        normalized_domain="example.com",
    )
    async with session_scope(migrated) as sess:
        await upsert_source(sess, source)

    for day, key in ((3, "week1"), (17, "week3")):
        await _seed_batch_summary(
            migrated,
            source=source,
            published_at=datetime(2026, 7, day, 12, 0, tzinfo=UTC),
            key=key,
        )

    gateway = _CountingGateway()
    pipeline = _pipeline(
        cadence=Cadence.MONTHLY,
        settings=test_settings,
        session_factory=migrated,
        gateway=gateway,
        clock=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
    )

    result = await pipeline.run()

    assert result.covered_start == date(2026, 7, 1)
    assert result.covered_end == date(2026, 7, 31)
    assert result.summaries_selected == 2
    assert result.is_no_content is False
    assert result.brief_id is not None


@pytest.mark.asyncio
async def test_batch_summary_cited_by_daily_brief_is_still_eligible_for_weekly_brief(
    migrated: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    """Spec success criterion 4: cadence-independent citation tracking - a
    summary cited by a Daily brief must still be independently selected by
    that week's Weekly brief."""
    source = Source(
        stable_id="periodic-integration-src-cross-cadence",
        name="Cross Cadence Source",
        normalized_domain="example.com",
    )
    async with session_scope(migrated) as sess:
        await upsert_source(sess, source)

    published_at = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    summary = await _seed_batch_summary(
        migrated, source=source, published_at=published_at, key="cross-cadence"
    )

    daily_brief = Brief(
        cadence=Cadence.DAILY,
        covered_start=date(2026, 7, 8),
        covered_end=date(2026, 7, 8),
        content="Daily brief citing the summary.",
        cited_batch_summary_ids=[summary.id],
        cited_article_ids=[],
        created_by_run_id=summary.id,
    )
    async with session_scope(migrated) as sess:
        await save_brief(sess, daily_brief)

    gateway = _CountingGateway()
    pipeline = _pipeline(
        cadence=Cadence.WEEKLY,
        settings=test_settings,
        session_factory=migrated,
        gateway=gateway,
        clock=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
    )

    result = await pipeline.run()

    assert result.is_no_content is False
    assert result.summaries_selected == 1
    assert result.brief_id is not None
