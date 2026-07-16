"""Daily brief pipeline orchestrating ingestion, batching, summarization, and workflow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from analyst_engine.batching.batcher import batch_articles
from analyst_engine.config import Settings
from analyst_engine.domain.models import (
    ArticleBatch,
    BatchSummary,
    Cadence,
    IngestionStatus,
    WorkflowRun,
    WorkflowStatus,
)
from analyst_engine.ingestion.models import IngestionResult
from analyst_engine.ingestion.service import IngestionService
from analyst_engine.models.gateway import ModelGateway
from analyst_engine.persistence.engine import session_scope
from analyst_engine.persistence.repositories import (
    get_article_batch_by_key,
    get_articles_by_ids,
    get_batch_summary_by_identity,
    get_brief_by_cadence_interval,
    get_sources_by_ids,
    get_workflow_run_by_idempotency,
    is_batch_summary_cited,
    list_due_source_feeds,
    list_eligible_unbatched_articles,
    save_article_batch,
    save_batch_summary,
)
from analyst_engine.summarization.summarizer import SummaryValidationError, summarize_batch
from analyst_engine.workflows.runner import WorkflowRunner


@dataclass(frozen=True)
class DailyPipelineResult:
    target_date: date
    feeds_polled: int
    articles_succeeded: int
    articles_duplicate: int
    articles_failed: int
    batches_created: int
    batches_reused: int
    summaries_created: int
    summaries_reused: int
    summaries_selected: int
    is_no_content: bool
    workflow_run_id: UUID | None
    workflow_status: WorkflowStatus | None
    brief_id: UUID | None


class DailyBriefPipeline:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        ingestion_service: IngestionService,
        runner: WorkflowRunner,
        gateway: ModelGateway,
        settings: Settings,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._ingestion_service = ingestion_service
        self._runner = runner
        self._gateway = gateway
        self._settings = settings
        self._clock = clock

    async def run(self, target_date: date) -> DailyPipelineResult:
        async with session_scope(self._session_factory) as session:
            due_feeds = await list_due_source_feeds(session, self._clock())
        due_feeds = due_feeds[: self._settings.max_feeds_per_run]

        articles_succeeded = articles_duplicate = articles_failed = 0
        for feed in due_feeds:
            results: list[IngestionResult] = await self._ingestion_service.poll_feed(feed)
            for result in results:
                if result.status is IngestionStatus.SUCCEEDED:
                    articles_succeeded += 1
                elif result.status is IngestionStatus.DUPLICATE:
                    articles_duplicate += 1
                else:
                    articles_failed += 1

        async with session_scope(self._session_factory) as session:
            eligible_articles = await list_eligible_unbatched_articles(
                session, target_date, self._settings.allowed_languages
            )
        eligible_articles = eligible_articles[: self._settings.max_articles_per_run]

        batcher_result = batch_articles(
            eligible_articles,
            title_similarity_threshold=self._settings.title_similarity_threshold,
            grouping_algorithm_version=self._settings.grouping_algorithm_version,
        )
        resolved_batches: list[ArticleBatch] = []
        batches_created = batches_reused = 0
        async with session_scope(self._session_factory) as session:
            for batch in batcher_result.batches:
                existing_batch = await get_article_batch_by_key(session, batch.batch_key)
                if existing_batch is not None:
                    resolved_batches.append(existing_batch)
                    batches_reused += 1
                else:
                    saved = await save_article_batch(session, batch)
                    resolved_batches.append(saved)
                    batches_created += 1

        summaries_by_batch: dict[UUID, BatchSummary] = {}
        summaries_created = summaries_reused = 0
        for batch in resolved_batches:
            async with session_scope(self._session_factory) as session:
                existing_summary = await get_batch_summary_by_identity(
                    session,
                    batch.id,
                    self._settings.batch_summary_model,
                    self._settings.batch_summary_prompt_version,
                )
            if existing_summary is not None:
                summaries_reused += 1
                summary = existing_summary
            else:
                async with session_scope(self._session_factory) as session:
                    batch_articles_rows = await get_articles_by_ids(session, batch.article_ids)
                    source_ids = list(
                        {a.source_id for a in batch_articles_rows if a.source_id is not None}
                    )
                    sources = await get_sources_by_ids(session, source_ids)
                try:
                    summary, _usage = await summarize_batch(
                        batch,
                        batch_articles_rows,
                        sources,
                        gateway=self._gateway,
                        model=self._settings.batch_summary_model,
                        prompt_version=self._settings.batch_summary_prompt_version,
                        correlation_id=f"daily:{target_date.isoformat()}:{batch.id}",
                    )
                except SummaryValidationError:
                    continue
                async with session_scope(self._session_factory) as session:
                    summary = await save_batch_summary(session, summary)
                summaries_created += 1
            summaries_by_batch[batch.id] = summary

        selected_summaries: list[BatchSummary] = []
        for batch in resolved_batches:
            batch_summary = summaries_by_batch.get(batch.id)
            if batch_summary is None:
                continue
            async with session_scope(self._session_factory) as session:
                batch_articles_rows = await get_articles_by_ids(session, batch.article_ids)
                already_cited = await is_batch_summary_cited(
                    session,
                    batch_summary.id,
                    Cadence.DAILY,
                    exclude_covered_start=target_date,
                    exclude_covered_end=target_date,
                )
            if already_cited:
                continue
            published_dates = {a.published_at.date() for a in batch_articles_rows}
            if target_date not in published_dates:
                continue
            if any(d > target_date for d in published_dates):
                continue
            selected_summaries.append(batch_summary)

        if not selected_summaries:
            # An already-terminal run for this exact date means this is a
            # retry after a prior success (or failure), not genuinely a
            # no-content day - list_eligible_unbatched_articles naturally
            # returns nothing once articles are already batched, so Steps
            # 2-5 finding nothing new is expected on a same-date retry, not
            # evidence there was never anything to report. Let run_daily's
            # own idempotency-key lookup return the existing terminal run
            # (spec 9: "Pipeline retry reuses ... terminal workflow runs").
            date_key = target_date.isoformat()
            idempotency_key = f"{Cadence.DAILY.value}:{date_key}:{date_key}"
            async with session_scope(self._session_factory) as session:
                existing_run = await get_workflow_run_by_idempotency(session, idempotency_key)
            if existing_run is None or existing_run.status not in (
                WorkflowStatus.SUCCEEDED,
                WorkflowStatus.FAILED,
            ):
                return DailyPipelineResult(
                    target_date=target_date,
                    feeds_polled=len(due_feeds),
                    articles_succeeded=articles_succeeded,
                    articles_duplicate=articles_duplicate,
                    articles_failed=articles_failed,
                    batches_created=batches_created,
                    batches_reused=batches_reused,
                    summaries_created=summaries_created,
                    summaries_reused=summaries_reused,
                    summaries_selected=0,
                    is_no_content=True,
                    workflow_run_id=None,
                    workflow_status=None,
                    brief_id=None,
                )

        workflow_run: WorkflowRun = await self._runner.run_daily(
            target_date, batch_summaries=selected_summaries
        )

        brief_id: UUID | None = None
        if workflow_run.status is WorkflowStatus.SUCCEEDED:
            async with session_scope(self._session_factory) as session:
                brief = await get_brief_by_cadence_interval(
                    session, Cadence.DAILY, target_date, target_date
                )
                brief_id = brief.id if brief is not None else None

        return DailyPipelineResult(
            target_date=target_date,
            feeds_polled=len(due_feeds),
            articles_succeeded=articles_succeeded,
            articles_duplicate=articles_duplicate,
            articles_failed=articles_failed,
            batches_created=batches_created,
            batches_reused=batches_reused,
            summaries_created=summaries_created,
            summaries_reused=summaries_reused,
            summaries_selected=len(selected_summaries),
            is_no_content=False,
            workflow_run_id=workflow_run.id,
            workflow_status=workflow_run.status,
            brief_id=brief_id,
        )
