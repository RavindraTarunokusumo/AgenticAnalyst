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
)
from analyst_engine.models.gateway import ModelGateway, ModelTask, ModelUsage
from analyst_engine.persistence.engine import session_scope

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

        # batch or embed fallbacks
        result = output_schema(brief_content="batch", narrative_state={}, change_log=[])
        return result, ModelUsage(model="fake")

    def get_model_for_task(self, task: ModelTask) -> str:
        return "fake-model"

    async def embed(self, *, text: str, correlation_id: str) -> tuple[list[float], ModelUsage]:
        if self._embed_error is not None:
            raise self._embed_error
        vector = [float(len(text) % 7 + 1)] * 1536
        return vector, ModelUsage(model="fake-embed")


def make_source() -> Source:
    return Source(stable_id="test-src", name="Test", normalized_domain="example.com")


def make_article(source_id: uuid.UUID, published: date) -> Article:
    return Article(
        source_id=source_id,
        url=f"https://example.com/{published}",
        url_fingerprint=f"fp-{published}",
        title=f"Article {published}",
        published_at=datetime.combine(published, datetime.min.time(), tzinfo=UTC),
        cleaned_content=f"Clean body for {published}.",
    )


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


def make_brief(cadence: Cadence, start: date, end: date) -> Brief:
    return Brief(
        cadence=cadence,
        covered_start=start,
        covered_end=end,
        content=f"{cadence} brief",
        cited_batch_summary_ids=[uuid.uuid4()],
        cited_article_ids=[uuid.uuid4()],
        created_by_run_id=uuid.uuid4(),
    )


def make_narrative() -> NarrativeStateVersion:
    return NarrativeStateVersion(
        created_by_run_id=uuid.uuid4(),
        state={"version": 1},
        change_log=["init"],
    )


async def truncate_domain_tables(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Wipe all domain tables so each test starts from a clean slate.

    Repository/integration test modules that read DATABASE_URL (CI's shared
    Postgres service, not a per-module Testcontainer) all point at the same
    physical database with no other isolation between tests. Without this,
    a row inserted by one test/module collides with an identical fixture
    literal in another (unique constraints) or inflates unscoped COUNT/ORDER
    BY assertions in a later test.
    """
    async with session_scope(session_factory) as session:
        await session.execute(
            text(f"TRUNCATE TABLE {', '.join(_DOMAIN_TABLES)} RESTART IDENTITY CASCADE")
        )


def docker_endpoint_available() -> bool:
    """Return True if a Docker endpoint is reachable.

    Contract: docker.from_env(timeout=3), ping(), close().
    Returns True only on successful ping; False on any failure.
    No false positives from DOCKER_HOST presence or socket paths.
    """
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
