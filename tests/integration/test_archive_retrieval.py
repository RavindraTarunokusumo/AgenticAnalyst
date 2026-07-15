"""Integration tests for search_embeddings_by_similarity against real pgvector.

Spec (docs/superpowers/specs/2026-07-15-archive-retrieval-design.md) §8 requires
real nearest-neighbor ordering verified against a live Postgres+pgvector index -
no mocked-vector-math substitute is acceptable for the ordering assertion.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, date, datetime

import pytest
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from alembic import command
from analyst_engine.config import Settings
from analyst_engine.domain.models import Brief, Cadence, Embedding
from analyst_engine.persistence.engine import get_async_engine, get_session_factory, session_scope
from analyst_engine.persistence.repositories import (
    save_brief,
    save_embedding,
    search_embeddings_by_similarity,
)

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

_VECTOR_DIM = 1536


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
        dashscope_api_key="test-key-for-archive-retrieval",
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


def _unit_vector(axis: int) -> list[float]:
    vector = [0.0] * _VECTOR_DIM
    vector[axis] = 1.0
    return vector


def _blended_vector(axis_a: int, axis_b: int) -> list[float]:
    vector = [0.0] * _VECTOR_DIM
    vector[axis_a] = 0.5
    vector[axis_b] = 0.5
    return vector


def _make_brief(cadence: Cadence, covered: date, content: str) -> Brief:
    return Brief(
        cadence=cadence,
        covered_start=covered,
        covered_end=covered,
        content=content,
        cited_batch_summary_ids=[uuid.uuid4()],
        cited_article_ids=[],
        created_by_run_id=uuid.uuid4(),
        created_at=datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_search_orders_by_cosine_distance_nearest_first(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    # Query vector points exactly along axis 0.
    query_vector = _unit_vector(0)

    close_brief = _make_brief(Cadence.DAILY, date(2026, 7, 10), "closest match")
    medium_brief = _make_brief(Cadence.DAILY, date(2026, 7, 11), "medium match")
    far_brief = _make_brief(Cadence.DAILY, date(2026, 7, 12), "farthest match")

    async with session_scope(migrated) as sess:
        await save_brief(sess, close_brief)
        await save_brief(sess, medium_brief)
        await save_brief(sess, far_brief)
        # close: identical direction to query (cosine distance 0)
        await save_embedding(
            sess,
            Embedding(brief_id=close_brief.id, model="test-embed", vector=_unit_vector(0)),
        )
        # medium: 45 degrees off query (cosine distance ~0.293)
        await save_embedding(
            sess,
            Embedding(brief_id=medium_brief.id, model="test-embed", vector=_blended_vector(0, 1)),
        )
        # far: orthogonal to query (cosine distance 1)
        await save_embedding(
            sess,
            Embedding(brief_id=far_brief.id, model="test-embed", vector=_unit_vector(1)),
        )

    async with session_scope(migrated) as sess:
        results = await search_embeddings_by_similarity(sess, query_vector, cadence=None, limit=10)

    ordered_brief_ids = [brief.id for _embedding, brief in results]
    assert ordered_brief_ids == [close_brief.id, medium_brief.id, far_brief.id]

    # Distances strictly increase (nearest-first).
    similarities = []
    async with session_scope(migrated) as sess:
        for embedding_row, _brief_row in await search_embeddings_by_similarity(
            sess, query_vector, cadence=None, limit=10
        ):
            similarities.append(embedding_row.vector)
    assert similarities[0] == _unit_vector(0)
    assert similarities[2] == _unit_vector(1)


@pytest.mark.asyncio
async def test_search_filters_by_cadence(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    query_vector = _unit_vector(0)

    daily_brief = _make_brief(Cadence.DAILY, date(2026, 7, 10), "daily")
    weekly_brief = _make_brief(Cadence.WEEKLY, date(2026, 7, 6), "weekly")

    async with session_scope(migrated) as sess:
        await save_brief(sess, daily_brief)
        await save_brief(sess, weekly_brief)
        await save_embedding(
            sess, Embedding(brief_id=daily_brief.id, model="test-embed", vector=_unit_vector(0))
        )
        await save_embedding(
            sess, Embedding(brief_id=weekly_brief.id, model="test-embed", vector=_unit_vector(0))
        )

    async with session_scope(migrated) as sess:
        daily_only = await search_embeddings_by_similarity(
            sess, query_vector, cadence=Cadence.DAILY, limit=10
        )
        weekly_only = await search_embeddings_by_similarity(
            sess, query_vector, cadence=Cadence.WEEKLY, limit=10
        )
        unfiltered = await search_embeddings_by_similarity(
            sess, query_vector, cadence=None, limit=10
        )

    assert [brief.id for _e, brief in daily_only] == [daily_brief.id]
    assert [brief.id for _e, brief in weekly_only] == [weekly_brief.id]
    assert {brief.id for _e, brief in unfiltered} == {daily_brief.id, weekly_brief.id}


@pytest.mark.asyncio
async def test_search_respects_limit_and_returns_empty_for_no_embeddings(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    query_vector = _unit_vector(0)

    async with session_scope(migrated) as sess:
        empty = await search_embeddings_by_similarity(sess, query_vector, cadence=None, limit=10)
    assert empty == []

    briefs = [_make_brief(Cadence.DAILY, date(2026, 7, 1 + i), f"brief {i}") for i in range(3)]
    async with session_scope(migrated) as sess:
        for brief in briefs:
            await save_brief(sess, brief)
            await save_embedding(
                sess, Embedding(brief_id=brief.id, model="test-embed", vector=_unit_vector(0))
            )

    async with session_scope(migrated) as sess:
        limited = await search_embeddings_by_similarity(sess, query_vector, cadence=None, limit=2)
    assert len(limited) == 2
