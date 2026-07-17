"""Repository integration tests for topic CRUD and list_sources_for_topic."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic.config import Config
from fixtures import ensure_topic, truncate_domain_tables  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from alembic import command
from analyst_engine.config import Settings
from analyst_engine.domain.models import Source, Topic
from analyst_engine.persistence.engine import get_async_engine, get_session_factory, session_scope
from analyst_engine.persistence.repositories import (
    TopicInUseError,
    TopicNotFoundError,
    create_topic,
    delete_topic,
    get_topic,
    list_sources_for_topic,
    list_topics,
    update_topic,
    upsert_source,
)

try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    PostgresContainer = None  # type: ignore[import-untyped, unused-ignore]


pytestmark = pytest.mark.integration


def _docker_endpoint_available() -> bool:
    client = None
    try:
        import docker

        client = docker.from_env(timeout=3)  # type: ignore[attr-defined, unused-ignore]
        client.ping()
        return True
    except Exception:
        return False
    finally:
        if client is not None:
            with suppress(Exception):
                client.close()


@pytest.fixture(scope="session")
def pg_container():  # type: ignore[no-untyped-def, unused-ignore]
    if os.environ.get("DATABASE_URL"):
        yield None
        return
    if PostgresContainer is None:
        pytest.skip("integration database unavailable: no DATABASE_URL or testcontainers")
    if not _docker_endpoint_available():
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
        dashscope_api_key="test-key-for-persistence",
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


def _make_topic(
    *,
    name: str = "US-Iran war",
    description: str = "Nuclear talks and shipping",
    keywords: list[str] | None = None,
    interest_detail: str | None = None,
) -> Topic:
    return Topic(
        name=name,
        description=description,
        interest_detail=interest_detail,
        keywords=keywords if keywords is not None else ["iran", "nuclear", "hormuz"],
    )


@pytest.mark.asyncio
async def test_create_and_get_topic_round_trip(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    topic = _make_topic(interest_detail="Q: regions? A: Strait of Hormuz")

    async with session_scope(migrated) as sess:
        created = await create_topic(sess, topic)
        fetched = await get_topic(sess, topic.id)
        missing = await get_topic(sess, uuid4())

    assert created.id == topic.id
    assert created.name == topic.name
    assert created.description == topic.description
    assert created.interest_detail == topic.interest_detail
    assert created.keywords == ["iran", "nuclear", "hormuz"]
    assert fetched is not None
    assert fetched == created
    assert missing is None


@pytest.mark.asyncio
async def test_list_topics_orders_by_name_then_id(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    topics = [
        _make_topic(name="Zulu topic", keywords=["zulu"]),
        _make_topic(name="Alpha topic", keywords=["alpha"]),
        _make_topic(name="Alpha topic", keywords=["alpha-two"]),
    ]

    async with session_scope(migrated) as sess:
        for topic in topics:
            await create_topic(sess, topic)
        listed = await list_topics(sess)

    assert [t.name for t in listed] == ["Alpha topic", "Alpha topic", "Zulu topic"]
    alpha_rows = [t for t in listed if t.name == "Alpha topic"]
    assert alpha_rows[0].id < alpha_rows[1].id


@pytest.mark.asyncio
async def test_update_topic_edits_fields_keywords_and_bumps_updated_at(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    original = _make_topic(
        name="Original",
        description="Before",
        interest_detail="old detail",
        keywords=["before"],
    )
    # Force a known created/updated baseline so the bump is observable.
    created_at = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    original = original.model_copy(update={"created_at": created_at, "updated_at": created_at})

    async with session_scope(migrated) as sess:
        await create_topic(sess, original)
        before = await get_topic(sess, original.id)
        assert before is not None
        assert before.updated_at == created_at

        revised = original.model_copy(
            update={
                "name": "Revised",
                "description": "After",
                "interest_detail": "new detail",
                "keywords": ["after", "keywords"],
            }
        )
        updated = await update_topic(sess, revised)
        reread = await get_topic(sess, original.id)

    assert updated.name == "Revised"
    assert updated.description == "After"
    assert updated.interest_detail == "new detail"
    assert updated.keywords == ["after", "keywords"]
    assert updated.created_at == created_at
    assert updated.updated_at > created_at
    assert reread is not None
    assert reread == updated


@pytest.mark.asyncio
async def test_update_topic_missing_raises(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    ghost = _make_topic(name="Ghost", keywords=["ghost"])

    async with session_scope(migrated) as sess:
        with pytest.raises(TopicNotFoundError, match="topic not found"):
            await update_topic(sess, ghost)


@pytest.mark.asyncio
async def test_delete_topic_succeeds_when_unreferenced(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    topic = _make_topic(name="Disposable", keywords=["temp"])

    async with session_scope(migrated) as sess:
        await create_topic(sess, topic)
        await delete_topic(sess, topic.id)
        assert await get_topic(sess, topic.id) is None


@pytest.mark.asyncio
async def test_delete_topic_with_sources_attached_raises_topic_in_use(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    topic = _make_topic(name="Has sources", keywords=["keep"])
    source = Source(
        topic_id=topic.id,
        stable_id="reuters-topic-src",
        name="Reuters",
        normalized_domain="reuters.com",
    )

    async with session_scope(migrated) as sess:
        await create_topic(sess, topic)
        await ensure_topic(sess)
        await upsert_source(sess, source)

    # Separate session: IntegrityError from RESTRICT leaves the session
    # needing rollback; session_scope must absorb that without poisoning later work.
    async with session_scope(migrated) as sess:
        with pytest.raises(TopicInUseError, match="still referenced"):
            await delete_topic(sess, topic.id)

    async with session_scope(migrated) as sess:
        still_there = await get_topic(sess, topic.id)
        sources = await list_sources_for_topic(sess, topic.id)

    assert still_there is not None
    assert still_there.id == topic.id
    assert [s.stable_id for s in sources] == ["reuters-topic-src"]


@pytest.mark.asyncio
async def test_delete_topic_missing_raises(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(migrated) as sess:
        with pytest.raises(TopicNotFoundError, match="topic not found"):
            await delete_topic(sess, uuid4())


@pytest.mark.asyncio
async def test_list_sources_for_topic_filters_and_orders_by_stable_id(
    migrated: async_sessionmaker[AsyncSession],
) -> None:
    topic_a = _make_topic(name="Topic A", keywords=["a"])
    topic_b = _make_topic(name="Topic B", keywords=["b"])
    sources = [
        Source(
            topic_id=topic_a.id,
            stable_id="zeta-src",
            name="Zeta",
            normalized_domain="zeta.example",
        ),
        Source(
            topic_id=topic_a.id,
            stable_id="alpha-src",
            name="Alpha",
            normalized_domain="alpha.example",
        ),
        Source(
            topic_id=topic_b.id,
            stable_id="other-src",
            name="Other",
            normalized_domain="other.example",
        ),
    ]

    async with session_scope(migrated) as sess:
        await create_topic(sess, topic_a)
        await create_topic(sess, topic_b)
        await ensure_topic(sess)
        for source in sources:
            await upsert_source(sess, source)
        listed_a = await list_sources_for_topic(sess, topic_a.id)
        listed_b = await list_sources_for_topic(sess, topic_b.id)
        empty = await list_sources_for_topic(sess, uuid4())

    assert [s.stable_id for s in listed_a] == ["alpha-src", "zeta-src"]
    assert all(s.topic_id == topic_a.id for s in listed_a)
    assert [s.stable_id for s in listed_b] == ["other-src"]
    assert empty == []
