"""Offline unit tests for DailyBriefPipeline orchestration."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest

from analyst_engine.batching.batcher import batch_articles
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
    SourceFeed,
    WorkflowRun,
    WorkflowStatus,
)
from analyst_engine.ingestion.models import IngestionResult
from analyst_engine.models.gateway import ModelGateway, ModelTask, ModelUsage
from analyst_engine.pipeline.daily_brief import DailyBriefPipeline
from analyst_engine.summarization.summarizer import SummaryValidationError

_TARGET_DATE = date(2026, 7, 13)
_FIXED_NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
_SOURCE_ID = UUID("11111111-1111-1111-1111-111111111111")
_RUN_ID = UUID("22222222-2222-2222-2222-222222222222")
_BRIEF_ID = UUID("33333333-3333-3333-3333-333333333333")
_SUMMARY_ID = UUID("44444444-4444-4444-4444-444444444444")


def _settings() -> Settings:
    return Settings(
        dashscope_api_key="test-key",
        database_url="postgresql+asyncpg://user:pass@localhost:5432/testdb",
        batch_summary_model="qwen3.5-flash",
        batch_summary_prompt_version="v1",
        title_similarity_threshold=0.35,
        grouping_algorithm_version="v1",
        allowed_languages=["en"],
    )


def _source() -> Source:
    return Source(
        id=_SOURCE_ID,
        stable_id="pipeline-src",
        name="Pipeline Source",
        normalized_domain="example.com",
    )


def _article(
    *,
    article_id: UUID | None = None,
    published: date = _TARGET_DATE,
    title: str = "Daily Market Update Story",
    fingerprint: str | None = None,
) -> Article:
    article_uuid = article_id or uuid4()
    return Article(
        id=article_uuid,
        source_id=_SOURCE_ID,
        url=f"https://example.com/{article_uuid}",
        url_fingerprint=fingerprint or f"fp-{article_uuid}",
        title=title,
        published_at=datetime.combine(published, datetime.min.time(), tzinfo=UTC),
        language="en",
        cleaned_content=f"Clean body for {title}.",
    )


def _batch(articles: list[Article]) -> ArticleBatch:
    return ArticleBatch(
        article_ids=[article.id for article in articles],
        batch_key="batch:" + ",".join(str(article.id) for article in articles),
        grouping_method=GroupingMethod.TITLE_TOKEN_JACCARD,
        embedding_model="none",
    )


def _summary(batch: ArticleBatch, articles: list[Article]) -> BatchSummary:
    return BatchSummary(
        id=_SUMMARY_ID,
        batch_id=batch.id,
        model="qwen3.5-flash",
        prompt_version="v1",
        summary="Batch summary.",
        citations=[Citation(article_id=articles[0].id, excerpt=articles[0].cleaned_content)],
    )


class _FakeIngestionService:
    def __init__(self, results: list[IngestionResult] | None = None) -> None:
        self.results = results or []
        self.poll_calls: list[SourceFeed] = []

    async def poll_feed(self, feed: SourceFeed) -> list[IngestionResult]:
        self.poll_calls.append(feed)
        return list(self.results)


class _FakeRunner:
    def __init__(self, workflow_run: WorkflowRun) -> None:
        self.workflow_run = workflow_run
        self.run_daily = AsyncMock(return_value=workflow_run)


class _FakeGateway(ModelGateway):
    async def generate(
        self,
        *,
        task: ModelTask,
        messages: list[dict[str, str]],
        output_schema: type[Any],
        correlation_id: str,
    ) -> tuple[Any, ModelUsage]:
        raise AssertionError("gateway.generate should not be called in unit tests")

    def get_model_for_task(self, task: ModelTask) -> str:
        return "fake"

    async def embed(self, *, text: str, correlation_id: str) -> tuple[list[float], ModelUsage]:
        raise AssertionError("gateway.embed should not be called in unit tests")


class _PipelineHarness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.due_feeds: list[SourceFeed] = []
        self.eligible_articles: list[Article] = []
        self.existing_batches: dict[str, ArticleBatch] = {}
        self.saved_batches: list[ArticleBatch] = []
        self.existing_summaries: dict[tuple[UUID, str, str], BatchSummary] = {}
        self.saved_summaries: list[BatchSummary] = []
        self.articles_by_id: dict[UUID, Article] = {}
        self.sources_by_id: dict[UUID, Source] = {}
        self.cited_daily_summary_intervals: dict[UUID, tuple[date, date]] = {}
        self.brief_by_interval: Brief | None = None
        self.summarize_calls: list[tuple[UUID, str]] = []
        self.existing_workflow_run_by_key: dict[str, WorkflowRun] = {}

        @asynccontextmanager
        async def fake_session_scope(_factory: object) -> Any:
            yield object()

        async def fake_list_due(_session: object, _now: datetime) -> list[SourceFeed]:
            return list(self.due_feeds)

        async def fake_list_eligible(
            _session: object, _before_date: date, _languages: list[str]
        ) -> list[Article]:
            return list(self.eligible_articles)

        async def fake_get_batch_by_key(_session: object, batch_key: str) -> ArticleBatch | None:
            return self.existing_batches.get(batch_key)

        async def fake_save_batch(_session: object, batch: ArticleBatch) -> ArticleBatch:
            self.saved_batches.append(batch)
            return batch

        async def fake_get_summary_by_identity(
            _session: object, batch_id: UUID, model: str, prompt_version: str
        ) -> BatchSummary | None:
            return self.existing_summaries.get((batch_id, model, prompt_version))

        async def fake_get_articles(_session: object, article_ids: list[UUID]) -> list[Article]:
            return [self.articles_by_id[article_id] for article_id in article_ids]

        async def fake_get_sources(_session: object, source_ids: list[UUID]) -> list[Source]:
            return [self.sources_by_id[source_id] for source_id in source_ids]

        async def fake_save_summary(_session: object, summary: BatchSummary) -> BatchSummary:
            self.saved_summaries.append(summary)
            return summary

        async def fake_is_cited(
            _session: object,
            batch_summary_id: UUID,
            cadence: Cadence,
            *,
            exclude_covered_start: date | None = None,
            exclude_covered_end: date | None = None,
        ) -> bool:
            if cadence is not Cadence.DAILY:
                return False
            interval = self.cited_daily_summary_intervals.get(batch_summary_id)
            if interval is None:
                return False
            return (exclude_covered_start, exclude_covered_end) != interval

        async def fake_get_workflow_run_by_idempotency(
            _session: object, idempotency_key: str
        ) -> WorkflowRun | None:
            return self.existing_workflow_run_by_key.get(idempotency_key)

        async def fake_get_brief(
            _session: object, cadence: Cadence, start: date, end: date
        ) -> Brief | None:
            if self.brief_by_interval is None:
                return None
            if (
                self.brief_by_interval.cadence is cadence
                and self.brief_by_interval.covered_start == start
                and self.brief_by_interval.covered_end == end
            ):
                return self.brief_by_interval
            return None

        async def fake_summarize_batch(
            batch: ArticleBatch,
            articles: list[Article],
            sources: list[Source],
            *,
            gateway: ModelGateway,
            model: str,
            prompt_version: str,
            correlation_id: str,
        ) -> tuple[BatchSummary, ModelUsage]:
            self.summarize_calls.append((batch.id, correlation_id))
            return _summary(batch, articles), ModelUsage(model=model)

        monkeypatch.setattr("analyst_engine.pipeline.daily_brief.session_scope", fake_session_scope)
        monkeypatch.setattr(
            "analyst_engine.pipeline.daily_brief.list_due_source_feeds", fake_list_due
        )
        monkeypatch.setattr(
            "analyst_engine.pipeline.daily_brief.list_eligible_unbatched_articles",
            fake_list_eligible,
        )
        monkeypatch.setattr(
            "analyst_engine.pipeline.daily_brief.get_article_batch_by_key", fake_get_batch_by_key
        )
        monkeypatch.setattr(
            "analyst_engine.pipeline.daily_brief.save_article_batch", fake_save_batch
        )
        monkeypatch.setattr(
            "analyst_engine.pipeline.daily_brief.get_batch_summary_by_identity",
            fake_get_summary_by_identity,
        )
        monkeypatch.setattr(
            "analyst_engine.pipeline.daily_brief.get_articles_by_ids", fake_get_articles
        )
        monkeypatch.setattr(
            "analyst_engine.pipeline.daily_brief.get_sources_by_ids", fake_get_sources
        )
        monkeypatch.setattr(
            "analyst_engine.pipeline.daily_brief.save_batch_summary", fake_save_summary
        )
        monkeypatch.setattr(
            "analyst_engine.pipeline.daily_brief.is_batch_summary_cited", fake_is_cited
        )
        monkeypatch.setattr(
            "analyst_engine.pipeline.daily_brief.get_workflow_run_by_idempotency",
            fake_get_workflow_run_by_idempotency,
        )
        monkeypatch.setattr(
            "analyst_engine.pipeline.daily_brief.get_brief_by_cadence_interval", fake_get_brief
        )
        monkeypatch.setattr(
            "analyst_engine.pipeline.daily_brief.summarize_batch", fake_summarize_batch
        )

    def seed_eligible_batch(self) -> tuple[list[Article], ArticleBatch, BatchSummary]:
        source = _source()
        articles = [
            _article(title="Daily Market Update One", fingerprint="fp-one"),
            _article(title="Daily Market Update Two", fingerprint="fp-two"),
            _article(title="Daily Market Update Three", fingerprint="fp-three"),
        ]
        settings = _settings()
        batch = batch_articles(
            articles,
            title_similarity_threshold=settings.title_similarity_threshold,
            grouping_algorithm_version=settings.grouping_algorithm_version,
        ).batches[0]
        summary = _summary(batch, articles)
        self.eligible_articles = articles
        self.articles_by_id = {article.id: article for article in articles}
        self.sources_by_id = {source.id: source}
        return articles, batch, summary

    def build_pipeline(self, runner: _FakeRunner) -> DailyBriefPipeline:
        return DailyBriefPipeline(
            session_factory=Mock(),
            ingestion_service=_FakeIngestionService(),  # type: ignore[arg-type]
            runner=runner,  # type: ignore[arg-type]
            gateway=_FakeGateway(),
            settings=_settings(),
            clock=lambda: _FIXED_NOW,
        )


@pytest.mark.asyncio
async def test_no_eligible_articles_short_circuits_without_run_daily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _PipelineHarness(monkeypatch)
    runner = _FakeRunner(
        WorkflowRun(
            id=_RUN_ID,
            cadence=Cadence.DAILY,
            idempotency_key=f"daily:{_TARGET_DATE.isoformat()}:{_TARGET_DATE.isoformat()}",
            status=WorkflowStatus.SUCCEEDED,
        )
    )
    pipeline = harness.build_pipeline(runner)

    result = await pipeline.run(_TARGET_DATE)

    assert result.is_no_content is True
    assert result.summaries_selected == 0
    assert result.workflow_run_id is None
    runner.run_daily.assert_not_called()


@pytest.mark.asyncio
async def test_no_new_content_but_existing_terminal_run_still_calls_run_daily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry of a date that already has a terminal WorkflowRun (e.g. the
    articles are already batched, so list_eligible_unbatched_articles finds
    nothing new) must still call run_daily so its own idempotency-key lookup
    returns the existing run - this is the genuine idempotent-rerun path,
    distinct from a real no-content day where no run has ever been created.
    """
    harness = _PipelineHarness(monkeypatch)
    idempotency_key = f"daily:{_TARGET_DATE.isoformat()}:{_TARGET_DATE.isoformat()}"
    existing_run = WorkflowRun(
        id=_RUN_ID,
        cadence=Cadence.DAILY,
        idempotency_key=idempotency_key,
        status=WorkflowStatus.SUCCEEDED,
    )
    harness.existing_workflow_run_by_key[idempotency_key] = existing_run
    harness.brief_by_interval = Brief(
        id=_BRIEF_ID,
        cadence=Cadence.DAILY,
        covered_start=_TARGET_DATE,
        covered_end=_TARGET_DATE,
        content="Daily brief.",
        cited_batch_summary_ids=[_SUMMARY_ID],
        cited_article_ids=[uuid4()],
        created_by_run_id=_RUN_ID,
    )
    runner = _FakeRunner(existing_run)
    pipeline = harness.build_pipeline(runner)

    result = await pipeline.run(_TARGET_DATE)

    assert result.is_no_content is False
    assert result.workflow_run_id == _RUN_ID
    assert result.workflow_status is WorkflowStatus.SUCCEEDED
    assert result.brief_id == _BRIEF_ID
    runner.run_daily.assert_awaited_once()


@pytest.mark.asyncio
async def test_successful_pipeline_calls_run_daily_with_selected_summaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _PipelineHarness(monkeypatch)
    articles, _batch, summary = harness.seed_eligible_batch()
    workflow_run = WorkflowRun(
        id=_RUN_ID,
        cadence=Cadence.DAILY,
        idempotency_key=f"daily:{_TARGET_DATE.isoformat()}:{_TARGET_DATE.isoformat()}",
        status=WorkflowStatus.SUCCEEDED,
    )
    harness.brief_by_interval = Brief(
        id=_BRIEF_ID,
        cadence=Cadence.DAILY,
        covered_start=_TARGET_DATE,
        covered_end=_TARGET_DATE,
        content="Daily brief.",
        cited_batch_summary_ids=[summary.id],
        cited_article_ids=[article.id for article in articles],
        created_by_run_id=_RUN_ID,
    )
    runner = _FakeRunner(workflow_run)
    pipeline = harness.build_pipeline(runner)

    result = await pipeline.run(_TARGET_DATE)

    runner.run_daily.assert_awaited_once()
    await_args = runner.run_daily.await_args
    assert await_args is not None
    selected = await_args.kwargs["batch_summaries"]
    assert len(selected) == 1
    assert len(harness.saved_batches) == 1
    assert selected[0].batch_id == harness.saved_batches[0].id
    assert result.is_no_content is False
    assert result.batches_created == 1
    assert result.batches_reused == 0
    assert result.summaries_created == 1
    assert result.summaries_reused == 0
    assert result.summaries_selected == 1
    assert result.workflow_run_id == _RUN_ID
    assert result.workflow_status is WorkflowStatus.SUCCEEDED
    assert result.brief_id == _BRIEF_ID


@pytest.mark.asyncio
async def test_existing_batch_key_is_reused_without_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _PipelineHarness(monkeypatch)
    articles, batch, _summary = harness.seed_eligible_batch()
    existing = batch.model_copy(update={"id": uuid4(), "batch_key": batch.batch_key})
    harness.existing_batches[batch.batch_key] = existing
    runner = _FakeRunner(
        WorkflowRun(
            cadence=Cadence.DAILY,
            idempotency_key=f"daily:{_TARGET_DATE.isoformat()}:{_TARGET_DATE.isoformat()}",
            status=WorkflowStatus.SUCCEEDED,
        )
    )
    pipeline = harness.build_pipeline(runner)

    result = await pipeline.run(_TARGET_DATE)

    assert result.batches_reused == 1
    assert result.batches_created == 0
    assert harness.saved_batches == []
    assert len(harness.summarize_calls) == 1
    assert harness.summarize_calls[0][0] == existing.id


@pytest.mark.asyncio
async def test_existing_batch_summary_is_reused_without_summarize_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _PipelineHarness(monkeypatch)
    _articles, batch, summary = harness.seed_eligible_batch()
    harness.existing_batches[batch.batch_key] = batch
    harness.existing_summaries[(batch.id, "qwen3.5-flash", "v1")] = summary
    runner = _FakeRunner(
        WorkflowRun(
            cadence=Cadence.DAILY,
            idempotency_key=f"daily:{_TARGET_DATE.isoformat()}:{_TARGET_DATE.isoformat()}",
            status=WorkflowStatus.SUCCEEDED,
        )
    )
    pipeline = harness.build_pipeline(runner)

    result = await pipeline.run(_TARGET_DATE)

    assert result.summaries_reused == 1
    assert result.summaries_created == 0
    assert harness.summarize_calls == []
    assert harness.saved_summaries == []


@pytest.mark.asyncio
async def test_already_cited_daily_summary_is_excluded_from_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _PipelineHarness(monkeypatch)
    _articles, _batch, _summary = harness.seed_eligible_batch()
    # Cited by a PRIOR daily brief for a different date - must be excluded.
    # (A citation from _TARGET_DATE's own brief must NOT exclude it; that's
    # what makes same-date pipeline retries idempotent, covered separately.)
    harness.cited_daily_summary_intervals[_SUMMARY_ID] = (
        _TARGET_DATE - timedelta(days=1),
        _TARGET_DATE - timedelta(days=1),
    )
    runner = _FakeRunner(
        WorkflowRun(
            cadence=Cadence.DAILY,
            idempotency_key=f"daily:{_TARGET_DATE.isoformat()}:{_TARGET_DATE.isoformat()}",
            status=WorkflowStatus.SUCCEEDED,
        )
    )
    pipeline = harness.build_pipeline(runner)

    result = await pipeline.run(_TARGET_DATE)

    assert result.is_no_content is True
    assert result.summaries_selected == 0
    runner.run_daily.assert_not_called()


@pytest.mark.asyncio
async def test_summary_cited_by_this_run_own_prior_brief_is_not_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry of the SAME target_date after its own prior success must still
    select the summary its own brief already cites - this is what makes
    pipeline.run(target_date) idempotent (spec success criterion 7). Only
    citations from a DIFFERENT date's brief should exclude a summary.
    """
    harness = _PipelineHarness(monkeypatch)
    _articles, _batch, _summary = harness.seed_eligible_batch()
    harness.cited_daily_summary_intervals[_SUMMARY_ID] = (_TARGET_DATE, _TARGET_DATE)
    runner = _FakeRunner(
        WorkflowRun(
            cadence=Cadence.DAILY,
            idempotency_key=f"daily:{_TARGET_DATE.isoformat()}:{_TARGET_DATE.isoformat()}",
            status=WorkflowStatus.SUCCEEDED,
        )
    )
    pipeline = harness.build_pipeline(runner)

    result = await pipeline.run(_TARGET_DATE)

    assert result.is_no_content is False
    assert result.summaries_selected == 1
    runner.run_daily.assert_awaited_once()


@pytest.mark.asyncio
async def test_summary_without_article_on_target_date_is_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _PipelineHarness(monkeypatch)
    articles = [
        _article(
            title="Daily Market Update One",
            fingerprint="fp-one",
            published=date(2026, 7, 12),
        ),
        _article(
            title="Daily Market Update Two",
            fingerprint="fp-two",
            published=date(2026, 7, 12),
        ),
        _article(
            title="Daily Market Update Three",
            fingerprint="fp-three",
            published=date(2026, 7, 12),
        ),
    ]
    harness.eligible_articles = articles
    harness.articles_by_id = {article.id: article for article in articles}
    harness.sources_by_id = {_SOURCE_ID: _source()}
    runner = _FakeRunner(
        WorkflowRun(
            cadence=Cadence.DAILY,
            idempotency_key=f"daily:{_TARGET_DATE.isoformat()}:{_TARGET_DATE.isoformat()}",
            status=WorkflowStatus.SUCCEEDED,
        )
    )
    pipeline = harness.build_pipeline(runner)

    result = await pipeline.run(_TARGET_DATE)

    assert result.is_no_content is True
    runner.run_daily.assert_not_called()


@pytest.mark.asyncio
async def test_summary_with_article_after_target_date_is_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _PipelineHarness(monkeypatch)
    articles = [
        _article(title="Daily Market Update One", fingerprint="fp-one"),
        _article(title="Daily Market Update Two", fingerprint="fp-two"),
        _article(
            title="Daily Market Update Three",
            fingerprint="fp-three",
            published=date(2026, 7, 14),
        ),
    ]
    harness.eligible_articles = articles
    harness.articles_by_id = {article.id: article for article in articles}
    harness.sources_by_id = {_SOURCE_ID: _source()}
    runner = _FakeRunner(
        WorkflowRun(
            cadence=Cadence.DAILY,
            idempotency_key=f"daily:{_TARGET_DATE.isoformat()}:{_TARGET_DATE.isoformat()}",
            status=WorkflowStatus.SUCCEEDED,
        )
    )
    pipeline = harness.build_pipeline(runner)

    result = await pipeline.run(_TARGET_DATE)

    assert result.is_no_content is True
    runner.run_daily.assert_not_called()


@pytest.mark.asyncio
async def test_summary_validation_error_skips_one_batch_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _PipelineHarness(monkeypatch)
    source = _source()
    # Titles deliberately share zero tokens across groups (not even ordinal
    # suffixes like "One"/"Two") - the greedy batcher compares every candidate
    # against a fixed seed, so any shared token (including a shared "One")
    # would pull articles from the other group into the same batch.
    batch_one_articles = [
        _article(title="Daily Market Update Alpha", fingerprint="fp-b1-1"),
        _article(title="Daily Market Update Beta", fingerprint="fp-b1-2"),
        _article(title="Daily Market Update Gamma", fingerprint="fp-b1-3"),
    ]
    batch_two_articles = [
        _article(title="Weather Forecast Report Monday", fingerprint="fp-b2-1"),
        _article(title="Weather Forecast Report Tuesday", fingerprint="fp-b2-2"),
        _article(title="Weather Forecast Report Wednesday", fingerprint="fp-b2-3"),
    ]
    harness.eligible_articles = batch_one_articles + batch_two_articles
    harness.articles_by_id = {article.id: article for article in harness.eligible_articles}
    harness.sources_by_id = {source.id: source}

    failing_batch_ids: set[UUID] = set()

    async def flaky_summarize(
        batch: ArticleBatch,
        articles: list[Article],
        sources: list[Source],
        *,
        gateway: ModelGateway,
        model: str,
        prompt_version: str,
        correlation_id: str,
    ) -> tuple[BatchSummary, ModelUsage]:
        failing_batch_ids.add(batch.id)
        if len(failing_batch_ids) == 1:
            raise SummaryValidationError("invalid citations")
        return _summary(batch, articles), ModelUsage(model=model)

    monkeypatch.setattr("analyst_engine.pipeline.daily_brief.summarize_batch", flaky_summarize)

    runner = _FakeRunner(
        WorkflowRun(
            cadence=Cadence.DAILY,
            idempotency_key=f"daily:{_TARGET_DATE.isoformat()}:{_TARGET_DATE.isoformat()}",
            status=WorkflowStatus.SUCCEEDED,
        )
    )
    pipeline = harness.build_pipeline(runner)

    result = await pipeline.run(_TARGET_DATE)

    assert result.summaries_created == 1
    assert result.summaries_selected == 1
    runner.run_daily.assert_awaited_once()
