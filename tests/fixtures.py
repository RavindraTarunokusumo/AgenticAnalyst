"""Deterministic fixtures and fakes for the harness (no external calls)."""

# mypy: ignore-errors
from __future__ import annotations

import uuid
from contextlib import suppress
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from analyst_engine.domain.models import (
    Article,
    ArticleBatch,
    BatchSummary,
    Brief,
    Cadence,
    Citation,
    GroupingMethod,
    NarrativeStateVersion,
    Source,
    Topic,
)
from analyst_engine.models.gateway import ModelGateway, ModelTask, ModelUsage
from analyst_engine.persistence.engine import session_scope

# Shared default topic for unit fixtures that do not care about multi-topic isolation.
# Integration tests that hit Postgres should persist a real Topic row first
# (see ensure_topic).
DEFAULT_TOPIC_ID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")

_DOMAIN_TABLES = (
    "workflow_run",
    "embedding",
    "brief",
    "prediction_expectation",
    "narrative_state_version",
    "ingestion_attempt",
    "source_feed",
    "batch_summary",
    "article_batch",
    "article",
    "source",
    "topic",
)


class FakeModelGateway(ModelGateway):
    """Deterministic fake that returns canned structured output."""

    def __init__(self, *, embed_error: Exception | None = None) -> None:
        self._embed_error = embed_error

    async def generate(
        self,
        *,
        task: ModelTask,
        messages: list[dict[str, str]],
        output_schema: type[Any],
        correlation_id: str,
    ) -> tuple[Any, ModelUsage]:
        if task in (
            ModelTask.FRONTIER_DAILY,
            ModelTask.FRONTIER_WEEKLY,
            ModelTask.FRONTIER_MONTHLY,
        ):
            result = output_schema(
                brief_content="Synthetic brief for " + correlation_id,
                narrative_state={"themes": ["test"]},
                change_log=["synthetic update"],
                expectations=[],
            )
            return result, ModelUsage(model="fake", prompt_tokens=10, completion_tokens=20)

        result = output_schema(brief_content="batch", narrative_state={}, change_log=[])
        return result, ModelUsage(model="fake")

    def get_model_for_task(self, task: ModelTask) -> str:
        return "fake-model"

    async def embed(self, *, text: str, correlation_id: str) -> tuple[list[float], ModelUsage]:
        if self._embed_error is not None:
            raise self._embed_error
        vector = [float(len(text) % 7 + 1)] * 1536
        return vector, ModelUsage(model="fake-embed")


def make_topic(
    *,
    topic_id: uuid.UUID | None = None,
    name: str = "Default Test Topic",
    description: str = "Shared fixture topic",
    keywords: list[str] | None = None,
) -> Topic:
    return Topic(
        id=topic_id or DEFAULT_TOPIC_ID,
        name=name,
        description=description,
        keywords=keywords if keywords is not None else ["fixture", "test"],
    )


def make_source(
    *,
    topic_id: uuid.UUID | None = None,
    stable_id: str = "test-src",
    name: str = "Test",
    normalized_domain: str = "example.com",
    source_id: uuid.UUID | None = None,
) -> Source:
    kwargs: dict[str, Any] = {
        "topic_id": topic_id or DEFAULT_TOPIC_ID,
        "stable_id": stable_id,
        "name": name,
        "normalized_domain": normalized_domain,
    }
    if source_id is not None:
        kwargs["id"] = source_id
    return Source(**kwargs)


def make_article(
    source_id: uuid.UUID | None,
    published: date,
    *,
    topic_id: uuid.UUID | None = None,
    title: str | None = None,
    url_fingerprint: str | None = None,
    language: str | None = "en",
    cleaned_content: str | None = None,
    article_id: uuid.UUID | None = None,
) -> Article:
    kwargs: dict[str, Any] = {
        "topic_id": topic_id or DEFAULT_TOPIC_ID,
        "source_id": source_id,
        "url": f"https://example.com/{published}",
        "url_fingerprint": url_fingerprint or f"fp-{published}",
        "title": title or f"Article {published}",
        "published_at": datetime.combine(published, datetime.min.time(), tzinfo=UTC),
        "cleaned_content": cleaned_content or f"Clean body for {published}.",
        "language": language,
    }
    if article_id is not None:
        kwargs["id"] = article_id
    return Article(**kwargs)


def make_batch(articles: list[Article]) -> ArticleBatch:
    article_ids = [a.id for a in articles]
    return ArticleBatch(
        article_ids=article_ids,
        batch_key="fake:" + ",".join(str(a) for a in article_ids),
        grouping_method=GroupingMethod.TITLE_TOKEN_JACCARD,
        embedding_model="fake",
    )


def make_summary(batch: ArticleBatch) -> BatchSummary:
    return BatchSummary(
        batch_id=batch.id,
        model="qwen3.5-flash",
        prompt_version="v1",
        summary="Batch summary.",
        citations=[Citation(article_id=batch.article_ids[0])],
    )


def make_brief(
    cadence: Cadence,
    start: date,
    end: date,
    *,
    topic_id: uuid.UUID | None = None,
    content: str | None = None,
    brief_id: uuid.UUID | None = None,
    created_by_run_id: uuid.UUID | None = None,
    cited_batch_summary_ids: list[uuid.UUID] | None = None,
    cited_article_ids: list[uuid.UUID] | None = None,
) -> Brief:
    kwargs: dict[str, Any] = {
        "topic_id": topic_id or DEFAULT_TOPIC_ID,
        "cadence": cadence,
        "covered_start": start,
        "covered_end": end,
        "content": content if content is not None else f"{cadence} brief",
        "cited_batch_summary_ids": cited_batch_summary_ids or [uuid.uuid4()],
        "cited_article_ids": cited_article_ids or [uuid.uuid4()],
        "created_by_run_id": created_by_run_id or uuid.uuid4(),
    }
    if brief_id is not None:
        kwargs["id"] = brief_id
    return Brief(**kwargs)


def make_narrative() -> NarrativeStateVersion:
    return NarrativeStateVersion(
        created_by_run_id=uuid.uuid4(),
        state={"version": 1},
        change_log=["init"],
    )


async def ensure_topic(session: AsyncSession, topic: Topic | None = None) -> Topic:
    """Persist ``topic`` (or the shared default) if it is not already present."""

    from analyst_engine.persistence.repositories import create_topic, get_topic

    candidate = topic if topic is not None else make_topic()
    existing = await get_topic(session, candidate.id)
    if existing is not None:
        return existing
    return await create_topic(session, candidate)


async def truncate_domain_tables(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Wipe all domain tables so each test starts from a clean slate."""

    async with session_scope(session_factory) as session:
        await session.execute(
            text(f"TRUNCATE TABLE {', '.join(_DOMAIN_TABLES)} RESTART IDENTITY CASCADE")
        )


def docker_endpoint_available() -> bool:
    """Return True if a Docker endpoint is reachable."""

    client = None
    try:
        import docker  # type: ignore[import-untyped]

        client = docker.from_env(timeout=3)
        client.ping()
        return True
    except Exception:
        return False
    finally:
        if client is not None:
            with suppress(Exception):
                client.close()
