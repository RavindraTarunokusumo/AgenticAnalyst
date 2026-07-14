"""Batch summarization with citation provenance validation."""

from __future__ import annotations

import re
from uuid import UUID

from analyst_engine.domain.models import Article, ArticleBatch, BatchSummary, Source
from analyst_engine.models.gateway import ModelGateway, ModelTask, ModelUsage
from analyst_engine.summarization.prompts import (
    BatchSummaryModelResult,
    build_batch_summary_messages,
)

_WHITESPACE_RE = re.compile(r"\s+")


class SummaryValidationError(RuntimeError):
    """Raised when model output fails citation or provenance validation."""


def _normalize_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _build_article_source_lookup(
    articles: list[Article],
    sources: list[Source],
) -> dict[UUID, tuple[Article, Source]]:
    source_by_id = {source.id: source for source in sources}
    lookup: dict[UUID, tuple[Article, Source]] = {}
    for article in articles:
        source = source_by_id.get(article.source_id)
        if source is None:
            raise SummaryValidationError(
                f"Article {article.id} references missing source {article.source_id}"
            )
        lookup[article.id] = (article, source)
    return lookup


def _validate_citations(
    result: BatchSummaryModelResult,
    articles: list[Article],
) -> None:
    if not result.citations:
        raise SummaryValidationError("Model returned zero citations")

    article_ids = {article.id for article in articles}
    content_by_id = {article.id: article.cleaned_content or "" for article in articles}

    for citation in result.citations:
        if citation.article_id not in article_ids:
            raise SummaryValidationError(
                f"Citation references article_id {citation.article_id} not in batch"
            )
        if citation.excerpt is None:
            continue
        normalized_excerpt = _normalize_whitespace(citation.excerpt)
        normalized_content = _normalize_whitespace(content_by_id[citation.article_id])
        if normalized_excerpt not in normalized_content:
            raise SummaryValidationError(
                f"Citation excerpt for article {citation.article_id} "
                "is not present in cleaned content"
            )


async def summarize_batch(
    batch: ArticleBatch,
    articles: list[Article],
    sources: list[Source],
    *,
    gateway: ModelGateway,
    model: str,
    prompt_version: str,
    correlation_id: str,
) -> tuple[BatchSummary, ModelUsage]:
    lookup = _build_article_source_lookup(articles, sources)
    batch_articles: list[tuple[Article, Source]] = []
    for article_id in batch.article_ids:
        pair = lookup.get(article_id)
        if pair is None:
            raise SummaryValidationError(
                f"Batch article_id {article_id} not found in provided articles"
            )
        batch_articles.append(pair)

    messages = build_batch_summary_messages(batch_articles, prompt_version=prompt_version)
    raw_result, usage = await gateway.generate(
        task=ModelTask.BATCH_SUMMARY,
        messages=messages,
        output_schema=BatchSummaryModelResult,
        correlation_id=correlation_id,
    )
    result = BatchSummaryModelResult.model_validate(raw_result)
    _validate_citations(result, articles)

    summary = BatchSummary(
        batch_id=batch.id,
        model=model,
        prompt_version=prompt_version,
        summary=result.summary,
        source_notes=result.source_notes,
        entities=result.entities,
        topics=result.topics,
        citations=result.citations,
    )
    return summary, usage
