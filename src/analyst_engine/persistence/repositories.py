"""Repository helpers.

All functions that perform writes accept an AsyncSession and operate within
the caller's transaction boundary. Lookups are also session-scoped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import any_, exists, literal, literal_column, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from analyst_engine.domain.models import (
    Article,
    ArticleBatch,
    BatchSummary,
    Brief,
    Cadence,
    Citation,
    Embedding,
    ExtractorKind,
    GroupingMethod,
    IngestionAttempt,
    IngestionStatus,
    NarrativeStateVersion,
    PredictionExpectation,
    Source,
    SourceFeed,
    WorkflowRun,
    WorkflowStatus,
)
from analyst_engine.persistence.models import (
    Article as ORMArticle,
)
from analyst_engine.persistence.models import (
    ArticleBatch as ORMArticleBatch,
)
from analyst_engine.persistence.models import (
    BatchSummary as ORMBatchSummary,
)
from analyst_engine.persistence.models import (
    Brief as ORMBrief,
)
from analyst_engine.persistence.models import (
    Embedding as ORMEmbedding,
)
from analyst_engine.persistence.models import (
    IngestionAttempt as ORMIngestionAttempt,
)
from analyst_engine.persistence.models import (
    NarrativeStateVersion as ORMNarrative,
)
from analyst_engine.persistence.models import (
    PredictionExpectation as ORMExpectation,
)
from analyst_engine.persistence.models import (
    Source as ORMSource,
)
from analyst_engine.persistence.models import (
    SourceFeed as ORMSourceFeed,
)
from analyst_engine.persistence.models import (
    WorkflowRun as ORMWorkflowRun,
)

# --- Simple mappers (domain <-> orm) for persistence boundary ---


def _article_to_orm(a: Article) -> ORMArticle:
    return ORMArticle(
        id=a.id,
        source_id=a.source_id,
        url=a.url,
        url_fingerprint=a.url_fingerprint,
        title=a.title,
        author=a.author,
        published_at=a.published_at,
        ingested_at=a.ingested_at,
        language=a.language,
        raw_content_hash=a.raw_content_hash,
        cleaned_content=a.cleaned_content,
    )


def _article_to_domain(row: ORMArticle) -> Article:
    return Article(
        id=row.id,
        source_id=row.source_id,
        url=row.url,
        url_fingerprint=row.url_fingerprint,
        title=row.title,
        author=row.author,
        published_at=row.published_at,
        ingested_at=row.ingested_at,
        language=row.language,
        raw_content_hash=row.raw_content_hash,
        cleaned_content=row.cleaned_content,
    )


def _source_to_domain(row: ORMSource) -> Source:
    return Source(
        id=row.id,
        stable_id=row.stable_id,
        name=row.name,
        normalized_domain=row.normalized_domain,
        created_at=row.created_at,
    )


def _source_feed_to_orm(feed: SourceFeed) -> ORMSourceFeed:
    return ORMSourceFeed(
        id=feed.id,
        source_id=feed.source_id,
        feed_url=feed.feed_url,
        feed_url_fingerprint=feed.feed_url_fingerprint,
        enabled=feed.enabled,
        poll_interval_minutes=feed.poll_interval_minutes,
        etag=feed.etag,
        last_modified=feed.last_modified,
        last_polled_at=feed.last_polled_at,
        last_success_at=feed.last_success_at,
        last_error_summary=feed.last_error_summary,
        created_at=feed.created_at,
        updated_at=feed.updated_at,
    )


def _source_feed_to_domain(row: ORMSourceFeed) -> SourceFeed:
    return SourceFeed(
        id=row.id,
        source_id=row.source_id,
        feed_url=row.feed_url,
        feed_url_fingerprint=row.feed_url_fingerprint,
        enabled=row.enabled,
        poll_interval_minutes=row.poll_interval_minutes,
        etag=row.etag,
        last_modified=row.last_modified,
        last_polled_at=row.last_polled_at,
        last_success_at=row.last_success_at,
        last_error_summary=row.last_error_summary,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _ingestion_attempt_to_orm(attempt: IngestionAttempt) -> ORMIngestionAttempt:
    return ORMIngestionAttempt(
        id=attempt.id,
        source_id=attempt.source_id,
        source_feed_id=attempt.source_feed_id,
        requested_url=attempt.requested_url,
        canonical_url=attempt.canonical_url,
        url_fingerprint=attempt.url_fingerprint,
        status=attempt.status.value,
        http_status=attempt.http_status,
        extractor=attempt.extractor.value if attempt.extractor is not None else None,
        article_id=attempt.article_id,
        error_code=attempt.error_code,
        error_summary=attempt.error_summary,
        started_at=attempt.started_at,
        completed_at=attempt.completed_at,
    )


def _ingestion_attempt_to_domain(row: ORMIngestionAttempt) -> IngestionAttempt:
    return IngestionAttempt(
        id=row.id,
        source_id=row.source_id,
        source_feed_id=row.source_feed_id,
        requested_url=row.requested_url,
        canonical_url=row.canonical_url,
        url_fingerprint=row.url_fingerprint,
        status=IngestionStatus(row.status),
        http_status=row.http_status,
        extractor=ExtractorKind(row.extractor) if row.extractor is not None else None,
        article_id=row.article_id,
        error_code=row.error_code,
        error_summary=row.error_summary,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def _batch_to_domain(row: ORMArticleBatch) -> ArticleBatch:
    return ArticleBatch(
        id=row.id,
        article_ids=list(row.article_ids),
        batch_key=row.batch_key,
        grouping_method=GroupingMethod(row.grouping_method),
        embedding_model=row.embedding_model,
        similarity_threshold=row.similarity_threshold,
        grouping_run_id=row.grouping_run_id,
        created_at=row.created_at,
    )


def _summary_to_domain(row: ORMBatchSummary) -> BatchSummary:
    return BatchSummary(
        id=row.id,
        batch_id=row.batch_id,
        model=row.model,
        prompt_version=row.prompt_version,
        summary=row.summary,
        source_notes=row.source_notes,
        entities=list(row.entities or []),
        topics=list(row.topics or []),
        citations=[
            Citation(article_id=c["article_id"], excerpt=c.get("excerpt"))
            for c in (row.citations or [])
        ],
        created_at=row.created_at,
    )


def _brief_to_domain(row: ORMBrief) -> Brief:
    return Brief(
        id=row.id,
        cadence=Cadence(row.cadence),
        covered_start=row.covered_start,
        covered_end=row.covered_end,
        content=row.content,
        cited_batch_summary_ids=list(row.cited_batch_summary_ids or []),
        cited_article_ids=list(row.cited_article_ids or []),
        narrative_state_version_id=row.narrative_state_version_id,
        created_by_run_id=row.created_by_run_id,
        created_at=row.created_at,
    )


def _batch_to_orm(b: ArticleBatch) -> ORMArticleBatch:
    return ORMArticleBatch(
        id=b.id,
        article_ids=b.article_ids,
        batch_key=b.batch_key,
        grouping_method=b.grouping_method.value
        if hasattr(b.grouping_method, "value")
        else str(b.grouping_method),
        embedding_model=b.embedding_model,
        similarity_threshold=b.similarity_threshold,
        grouping_run_id=b.grouping_run_id,
        created_at=b.created_at,
    )


def _summary_to_orm(s: BatchSummary) -> ORMBatchSummary:
    return ORMBatchSummary(
        id=s.id,
        batch_id=s.batch_id,
        model=s.model,
        prompt_version=s.prompt_version,
        summary=s.summary,
        source_notes=s.source_notes,
        entities=s.entities,
        topics=s.topics,
        citations=[c.model_dump(mode="json") for c in s.citations],
        created_at=s.created_at,
    )


def _brief_to_orm(b: Brief) -> ORMBrief:
    return ORMBrief(
        id=b.id,
        cadence=b.cadence.value,
        covered_start=b.covered_start,
        covered_end=b.covered_end,
        content=b.content,
        cited_batch_summary_ids=b.cited_batch_summary_ids,
        cited_article_ids=b.cited_article_ids,
        narrative_state_version_id=b.narrative_state_version_id,
        created_by_run_id=b.created_by_run_id,
        created_at=b.created_at,
    )


def _narrative_to_orm(n: NarrativeStateVersion) -> ORMNarrative:
    return ORMNarrative(
        id=n.id,
        parent_id=n.parent_id,
        created_by_run_id=n.created_by_run_id,
        state=n.state,
        change_log=n.change_log,
        created_at=n.created_at,
    )


def _expectation_to_orm(expectation: PredictionExpectation) -> ORMExpectation:
    return ORMExpectation(
        id=expectation.id,
        narrative_version_id=expectation.narrative_version_id,
        statement=expectation.statement,
        confidence=expectation.confidence,
        confirmation_criteria=expectation.confirmation_criteria,
        falsification_criteria=expectation.falsification_criteria,
        outcome_status=expectation.outcome_status,
        created_at=expectation.created_at,
    )


def _embedding_to_orm(e: Embedding) -> ORMEmbedding:
    return ORMEmbedding(
        id=e.id,
        brief_id=e.brief_id,
        model=e.model,
        vector=e.vector,
        meta=e.metadata,
        created_at=e.created_at,
    )


def _workflow_to_orm(w: WorkflowRun) -> ORMWorkflowRun:
    return ORMWorkflowRun(
        id=w.id,
        cadence=w.cadence.value,
        idempotency_key=w.idempotency_key,
        status=w.status.value,
        checkpoint_ref=w.checkpoint_ref,
        error_summary=w.error_summary,
        started_at=w.started_at,
        completed_at=w.completed_at,
    )


def _workflow_to_domain(row: ORMWorkflowRun) -> WorkflowRun:
    return WorkflowRun(
        id=row.id,
        cadence=Cadence(row.cadence),
        idempotency_key=row.idempotency_key,
        status=WorkflowStatus(row.status),
        checkpoint_ref=row.checkpoint_ref,
        error_summary=row.error_summary,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


class WorkflowRunPersistenceError(RuntimeError):
    """Base error for deterministic workflow-run persistence failures."""


class WorkflowRunAlreadyExistsError(WorkflowRunPersistenceError):
    """Raised when create conflicts with an existing stable identity."""


class WorkflowRunNotFoundError(WorkflowRunPersistenceError):
    """Raised when an update targets no workflow run."""


class WorkflowRunIdentityError(WorkflowRunPersistenceError):
    """Raised when an update attempts to change immutable identity fields."""


class InvalidWorkflowRunTransitionError(WorkflowRunPersistenceError):
    """Raised when a workflow-run lifecycle transition is not allowed."""


class IngestionAttemptNotFoundError(RuntimeError):
    """Raised when an update targets no ingestion attempt."""


_WORKFLOW_TRANSITIONS: dict[WorkflowStatus, frozenset[WorkflowStatus]] = {
    WorkflowStatus.PENDING: frozenset({WorkflowStatus.RUNNING, WorkflowStatus.FAILED}),
    WorkflowStatus.RUNNING: frozenset({WorkflowStatus.SUCCEEDED, WorkflowStatus.FAILED}),
    WorkflowStatus.SUCCEEDED: frozenset(),
    WorkflowStatus.FAILED: frozenset(),
    WorkflowStatus.RESUMABLE: frozenset(),
}


# --- Repositories / operations ---


async def upsert_source(session: AsyncSession, source: Source) -> Source:
    orm = (
        await session.execute(select(ORMSource).where(ORMSource.stable_id == source.stable_id))
    ).scalar_one_or_none()
    if orm is None:
        orm = ORMSource(
            id=source.id,
            stable_id=source.stable_id,
            name=source.name,
            normalized_domain=source.normalized_domain,
            created_at=source.created_at,
        )
        session.add(orm)
    # immutable after create in harness scope
    await session.flush()
    return source


async def save_article(session: AsyncSession, article: Article) -> Article:
    orm = _article_to_orm(article)
    session.add(orm)
    await session.flush()
    return article


async def save_article_batch(session: AsyncSession, batch: ArticleBatch) -> ArticleBatch:
    orm = _batch_to_orm(batch)
    session.add(orm)
    await session.flush()
    return batch


async def save_batch_summary(session: AsyncSession, summary: BatchSummary) -> BatchSummary:
    orm = _summary_to_orm(summary)
    session.add(orm)
    await session.flush()
    return summary


async def save_brief(session: AsyncSession, brief: Brief) -> Brief:
    orm = _brief_to_orm(brief)
    session.add(orm)
    await session.flush()
    return brief


async def save_narrative_version(
    session: AsyncSession, version: NarrativeStateVersion
) -> NarrativeStateVersion:
    orm = _narrative_to_orm(version)
    session.add(orm)
    await session.flush()
    return version


async def save_prediction_expectation(
    session: AsyncSession, expectation: PredictionExpectation
) -> PredictionExpectation:
    session.add(_expectation_to_orm(expectation))
    await session.flush()
    return expectation


async def save_embedding(session: AsyncSession, emb: Embedding) -> Embedding:
    orm = _embedding_to_orm(emb)
    session.add(orm)
    await session.flush()
    return emb


async def create_workflow_run(session: AsyncSession, run: WorkflowRun) -> WorkflowRun:
    orm = _workflow_to_orm(run)
    session.add(orm)
    try:
        await session.flush()
    except IntegrityError as error:
        raise WorkflowRunAlreadyExistsError(
            f"workflow run already exists: id={run.id}, idempotency_key={run.idempotency_key!r}"
        ) from error
    await session.refresh(orm)
    return _workflow_to_domain(orm)


async def update_workflow_run(session: AsyncSession, run: WorkflowRun) -> WorkflowRun:
    row = (
        await session.execute(
            select(ORMWorkflowRun).where(ORMWorkflowRun.id == run.id).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise WorkflowRunNotFoundError(f"workflow run not found: id={run.id}")
    if row.idempotency_key != run.idempotency_key or row.cadence != run.cadence.value:
        raise WorkflowRunIdentityError(
            "workflow run identity is immutable: "
            f"id={run.id}, idempotency_key={run.idempotency_key!r}, cadence={run.cadence.value}"
        )

    current_status = WorkflowStatus(row.status)
    if run.status != current_status and run.status not in _WORKFLOW_TRANSITIONS[current_status]:
        raise InvalidWorkflowRunTransitionError(
            f"invalid workflow run transition: {current_status.value} -> {run.status.value}"
        )

    row.status = run.status.value
    row.checkpoint_ref = run.checkpoint_ref
    row.error_summary = run.error_summary
    row.started_at = run.started_at
    row.completed_at = run.completed_at
    await session.flush()
    await session.refresh(row)
    return _workflow_to_domain(row)


async def claim_pending_workflow_run(session: AsyncSession, run: WorkflowRun) -> WorkflowRun | None:
    """Atomically claim a pending run; return None when another worker won."""

    claimed = (
        await session.execute(
            update(ORMWorkflowRun)
            .where(
                ORMWorkflowRun.id == run.id,
                ORMWorkflowRun.idempotency_key == run.idempotency_key,
                ORMWorkflowRun.cadence == run.cadence.value,
                ORMWorkflowRun.status == WorkflowStatus.PENDING.value,
            )
            .values(
                status=WorkflowStatus.RUNNING.value,
                checkpoint_ref=run.checkpoint_ref,
                error_summary=None,
                completed_at=None,
            )
            .returning(ORMWorkflowRun)
        )
    ).scalar_one_or_none()
    return None if claimed is None else _workflow_to_domain(claimed)


async def get_narrative_version_as_of(
    session: AsyncSession, before: date
) -> NarrativeStateVersion | None:
    """Load the narrative attached to the latest brief strictly before a run."""

    narrative_id = (
        await session.execute(
            select(ORMBrief.narrative_state_version_id)
            .where(
                ORMBrief.covered_end < before,
                ORMBrief.narrative_state_version_id.is_not(None),
            )
            .order_by(ORMBrief.covered_end.desc(), ORMBrief.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if narrative_id is None:
        return None
    row = (
        await session.execute(select(ORMNarrative).where(ORMNarrative.id == narrative_id))
    ).scalar_one_or_none()
    if row is None:
        return None
    return NarrativeStateVersion(
        id=row.id,
        parent_id=row.parent_id,
        created_by_run_id=row.created_by_run_id,
        state=dict(row.state),
        change_log=list(row.change_log),
        created_at=row.created_at,
    )


async def list_prior_briefs(session: AsyncSession, cadence: Cadence, before: date) -> list[Brief]:
    rows = (
        (
            await session.execute(
                select(ORMBrief)
                .where(ORMBrief.cadence == cadence.value, ORMBrief.covered_end < before)
                .order_by(ORMBrief.covered_end.desc())
                .limit(31)
            )
        )
        .scalars()
        .all()
    )
    return [
        Brief(
            id=row.id,
            cadence=Cadence(row.cadence),
            covered_start=row.covered_start,
            covered_end=row.covered_end,
            content=row.content,
            cited_batch_summary_ids=list(row.cited_batch_summary_ids),
            cited_article_ids=list(row.cited_article_ids),
            narrative_state_version_id=row.narrative_state_version_id,
            created_by_run_id=row.created_by_run_id,
            created_at=row.created_at,
        )
        for row in rows
    ]


async def save_workflow_run(session: AsyncSession, run: WorkflowRun) -> WorkflowRun:
    """Create a workflow run without overwrite semantics."""

    return await create_workflow_run(session, run)


async def get_workflow_run_by_idempotency(
    session: AsyncSession, idempotency_key: str
) -> WorkflowRun | None:
    row = (
        await session.execute(
            select(ORMWorkflowRun).where(ORMWorkflowRun.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return _workflow_to_domain(row)


async def get_brief_by_cadence_interval(
    session: AsyncSession, cadence: Cadence, start: date, end: date
) -> Brief | None:
    row = (
        await session.execute(
            select(ORMBrief).where(
                ORMBrief.cadence == cadence.value,
                ORMBrief.covered_start == start,
                ORMBrief.covered_end == end,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return Brief(
        id=row.id,
        cadence=cadence,
        covered_start=row.covered_start,
        covered_end=row.covered_end,
        content=row.content,
        cited_batch_summary_ids=list(row.cited_batch_summary_ids or []),
        cited_article_ids=list(row.cited_article_ids or []),
        narrative_state_version_id=row.narrative_state_version_id,
        created_by_run_id=row.created_by_run_id,
        created_at=row.created_at,
    )


async def list_batch_summaries_for_brief(
    session: AsyncSession, batch_ids: list[uuid.UUID]
) -> list[BatchSummary]:
    if not batch_ids:
        return []
    rows = (
        (
            await session.execute(
                select(ORMBatchSummary).where(ORMBatchSummary.batch_id.in_(batch_ids))
            )
        )
        .scalars()
        .all()
    )
    result: list[BatchSummary] = []
    for r in rows:
        result.append(
            BatchSummary(
                id=r.id,
                batch_id=r.batch_id,
                model=r.model,
                prompt_version=r.prompt_version,
                summary=r.summary,
                source_notes=r.source_notes,
                entities=list(r.entities or []),
                topics=list(r.topics or []),
                citations=[
                    Citation(article_id=c["article_id"], excerpt=c.get("excerpt"))
                    for c in (r.citations or [])
                ],
                created_at=r.created_at,
            )
        )
    return result


async def upsert_source_feed(session: AsyncSession, feed: SourceFeed) -> SourceFeed:
    row = (
        await session.execute(
            select(ORMSourceFeed).where(
                ORMSourceFeed.feed_url_fingerprint == feed.feed_url_fingerprint
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = _source_feed_to_orm(feed)
        session.add(row)
    else:
        row.enabled = feed.enabled
        row.poll_interval_minutes = feed.poll_interval_minutes
        row.etag = feed.etag
        row.last_modified = feed.last_modified
        row.last_polled_at = feed.last_polled_at
        row.last_success_at = feed.last_success_at
        row.last_error_summary = feed.last_error_summary
        row.updated_at = feed.updated_at
    await session.flush()
    await session.refresh(row)
    return _source_feed_to_domain(row)


async def get_source_feed_by_fingerprint(
    session: AsyncSession, fingerprint: str
) -> SourceFeed | None:
    row = (
        await session.execute(
            select(ORMSourceFeed).where(ORMSourceFeed.feed_url_fingerprint == fingerprint)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return _source_feed_to_domain(row)


async def list_due_source_feeds(session: AsyncSession, now: datetime) -> list[SourceFeed]:
    poll_due_at = ORMSourceFeed.last_polled_at + (
        ORMSourceFeed.poll_interval_minutes * literal_column("INTERVAL '1 minute'")
    )
    rows = (
        (
            await session.execute(
                select(ORMSourceFeed)
                .where(
                    ORMSourceFeed.enabled.is_(True),
                    or_(ORMSourceFeed.last_polled_at.is_(None), poll_due_at <= now),
                )
                .order_by(ORMSourceFeed.last_polled_at.asc().nulls_first())
            )
        )
        .scalars()
        .all()
    )
    return [_source_feed_to_domain(row) for row in rows]


async def list_sources(session: AsyncSession) -> list[Source]:
    rows = (
        (await session.execute(select(ORMSource).order_by(ORMSource.stable_id.asc())))
        .scalars()
        .all()
    )
    return [_source_to_domain(row) for row in rows]


async def get_source_by_stable_id(session: AsyncSession, stable_id: str) -> Source | None:
    row = (
        await session.execute(select(ORMSource).where(ORMSource.stable_id == stable_id))
    ).scalar_one_or_none()
    if row is None:
        return None
    return _source_to_domain(row)


async def record_ingestion_attempt(
    session: AsyncSession, attempt: IngestionAttempt
) -> IngestionAttempt:
    row = _ingestion_attempt_to_orm(attempt)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _ingestion_attempt_to_domain(row)


async def update_ingestion_attempt(
    session: AsyncSession, attempt: IngestionAttempt
) -> IngestionAttempt:
    row = (
        await session.execute(
            select(ORMIngestionAttempt).where(ORMIngestionAttempt.id == attempt.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise IngestionAttemptNotFoundError(f"ingestion attempt not found: id={attempt.id}")
    row.status = attempt.status.value
    row.http_status = attempt.http_status
    row.extractor = attempt.extractor.value if attempt.extractor is not None else None
    row.article_id = attempt.article_id
    row.error_code = attempt.error_code
    row.error_summary = attempt.error_summary
    row.completed_at = attempt.completed_at
    await session.flush()
    await session.refresh(row)
    return _ingestion_attempt_to_domain(row)


async def get_article_by_fingerprint(session: AsyncSession, fingerprint: str) -> Article | None:
    row = (
        await session.execute(select(ORMArticle).where(ORMArticle.url_fingerprint == fingerprint))
    ).scalar_one_or_none()
    if row is None:
        return None
    return _article_to_domain(row)


async def list_eligible_unbatched_articles(
    session: AsyncSession, before_date: date, languages: list[str]
) -> list[Article]:
    if not languages:
        return []
    published_before = datetime.combine(before_date + timedelta(days=1), time.min, tzinfo=UTC)
    batched = exists(
        select(1)
        .select_from(ORMArticleBatch)
        .where(ORMArticle.id == any_(ORMArticleBatch.article_ids))
    )
    rows = (
        (
            await session.execute(
                select(ORMArticle)
                .where(
                    ORMArticle.published_at < published_before,
                    ORMArticle.language.in_(languages),
                    ~batched,
                )
                .order_by(
                    ORMArticle.published_at.asc(),
                    ORMArticle.url_fingerprint.asc(),
                    ORMArticle.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return [_article_to_domain(row) for row in rows]


async def get_article_batch_by_key(session: AsyncSession, batch_key: str) -> ArticleBatch | None:
    row = (
        await session.execute(select(ORMArticleBatch).where(ORMArticleBatch.batch_key == batch_key))
    ).scalar_one_or_none()
    if row is None:
        return None
    return _batch_to_domain(row)


async def get_batch_summary_by_identity(
    session: AsyncSession, batch_id: uuid.UUID, model: str, prompt_version: str
) -> BatchSummary | None:
    row = (
        await session.execute(
            select(ORMBatchSummary).where(
                ORMBatchSummary.batch_id == batch_id,
                ORMBatchSummary.model == model,
                ORMBatchSummary.prompt_version == prompt_version,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return _summary_to_domain(row)


async def get_brief_by_id(session: AsyncSession, brief_id: uuid.UUID) -> Brief | None:
    row = (
        await session.execute(select(ORMBrief).where(ORMBrief.id == brief_id))
    ).scalar_one_or_none()
    if row is None:
        return None
    return _brief_to_domain(row)


async def get_articles_by_ids(session: AsyncSession, article_ids: list[uuid.UUID]) -> list[Article]:
    if not article_ids:
        return []
    rows = (
        (await session.execute(select(ORMArticle).where(ORMArticle.id.in_(article_ids))))
        .scalars()
        .all()
    )
    return [_article_to_domain(row) for row in rows]


async def get_sources_by_ids(session: AsyncSession, source_ids: list[uuid.UUID]) -> list[Source]:
    if not source_ids:
        return []
    rows = (
        (await session.execute(select(ORMSource).where(ORMSource.id.in_(source_ids))))
        .scalars()
        .all()
    )
    return [_source_to_domain(row) for row in rows]


async def is_batch_summary_cited(
    session: AsyncSession,
    batch_summary_id: uuid.UUID,
    cadence: Cadence,
    *,
    exclude_covered_start: date | None = None,
    exclude_covered_end: date | None = None,
) -> bool:
    conditions = [
        ORMBrief.cadence == cadence.value,
        literal(batch_summary_id) == any_(ORMBrief.cited_batch_summary_ids),
    ]
    if exclude_covered_start is not None and exclude_covered_end is not None:
        conditions.append(
            ~(
                (ORMBrief.covered_start == exclude_covered_start)
                & (ORMBrief.covered_end == exclude_covered_end)
            )
        )
    row = (await session.execute(select(ORMBrief.id).where(*conditions))).scalar_one_or_none()
    return row is not None
