"""Repository helpers.

All functions that perform writes accept an AsyncSession and operate within
the caller's transaction boundary. Lookups are also session-scoped.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from analyst_engine.domain.models import (
    Article,
    ArticleBatch,
    BatchSummary,
    Brief,
    Cadence,
    Embedding,
    NarrativeStateVersion,
    Source,
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
    NarrativeStateVersion as ORMNarrative,
)
from analyst_engine.persistence.models import (
    Source as ORMSource,
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


def _batch_to_orm(b: ArticleBatch) -> ORMArticleBatch:
    return ORMArticleBatch(
        id=b.id,
        article_ids=b.article_ids,
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
        citations=[c.model_dump() for c in s.citations],
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


async def save_embedding(session: AsyncSession, emb: Embedding) -> Embedding:
    orm = _embedding_to_orm(emb)
    session.add(orm)
    await session.flush()
    return emb


async def save_workflow_run(session: AsyncSession, run: WorkflowRun) -> WorkflowRun:
    orm = _workflow_to_orm(run)
    session.add(orm)
    await session.flush()
    return run


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
                citations=[  # best effort roundtrip
                    type("C", (), c)() for c in (r.citations or [])
                ],  # placeholder; real Citation constructed upstream
                created_at=r.created_at,
            )
        )
    return result
