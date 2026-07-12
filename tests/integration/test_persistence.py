"""Persistence integration tests using Testcontainers.

These tests:
- Spin a fresh pgvector container
- Apply the Alembic migrations from blank state
- Exercise repositories (including idempotency and citation lineage)
- Roundtrip a LangGraph checkpoint

They are skipped if Docker is unavailable in the environment.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest
from alembic.config import Config
from fixtures import docker_endpoint_available  # type: ignore[import-not-found]
from sqlalchemy import text
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
    WorkflowRun,
    WorkflowStatus,
)
from analyst_engine.persistence.checkpoints import get_async_checkpointer
from analyst_engine.persistence.engine import get_async_engine, get_session_factory, session_scope
from analyst_engine.persistence.repositories import (
    get_brief_by_cadence_interval,
    get_workflow_run_by_idempotency,
    save_article,
    save_article_batch,
    save_batch_summary,
    save_brief,
    save_workflow_run,
    upsert_source,
)

try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    PostgresContainer = None  # type: ignore[import-untyped, unused-ignore]


pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def pg_container():  # type: ignore[no-untyped-def, unused-ignore]
    if os.environ.get("DATABASE_URL"):
        yield None
        return
    if PostgresContainer is None:
        pytest.skip("integration database unavailable: no DATABASE_URL or testcontainers")
    if not docker_endpoint_available():
        pytest.skip("integration database unavailable: Docker endpoint not found")
    # After availability check, do not swallow startup errors. Let image/pull/auth/
    # config/Testcontainers/startup defects fail the gate (no broad skip here).
    container = PostgresContainer(
        image="pgvector/pgvector:0.8.0-pg16",
        username="analyst_test",
        password="testpw",
        dbname="analyst_test",
    )
    container.start()
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
    # Minimal settings with required fields for the test DB
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
    """Run alembic upgrade head against the test database."""
    # Set env for the migration env.py
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        cfg = Config("alembic.ini")
        # Ensure we target the right script location relative to cwd
        command.upgrade(cfg, "head")
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old


async def _verify_migration_roundtrip(database_url: str) -> None:
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        cfg = Config("alembic.ini")
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old


@pytest.mark.asyncio
async def test_blank_db_applies_migrations_and_basic_citation_path(
    test_settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    test_database_url: str,
) -> None:
    # Apply migrations (uses our initial migration + checkpoint tables)
    await _verify_migration_roundtrip(str(test_settings.database_url))

    # Verify tables exist via a raw query
    async with session_scope(session_factory) as sess:
        res = await sess.execute(text("SELECT to_regclass('public.article') IS NOT NULL"))
        assert res.scalar() is True
        res = await sess.execute(text("SELECT to_regclass('public.checkpoints') IS NOT NULL"))
        assert res.scalar() is True

    # Build citation path: source -> 3 articles (domain min 3-5) -> batch -> summary -> brief
    now = datetime.now(UTC)
    source = Source(  # type: ignore[call-arg, unused-ignore]
        stable_id="test-src",
        name="Test Source",
        normalized_domain="example.com",
    )
    article1 = Article(
        source_id=source.id,
        url="https://example.com/a1",
        url_fingerprint="fp-a1",
        title="Article One",
        published_at=now,
        cleaned_content="Clean body one.",
    )
    article2 = Article(
        source_id=source.id,
        url="https://example.com/a2",
        url_fingerprint="fp-a2",
        title="Article Two",
        published_at=now,
        cleaned_content="Clean body two.",
    )
    article3 = Article(
        source_id=source.id,
        url="https://example.com/a3",
        url_fingerprint="fp-a3",
        title="Article Three",
        published_at=now,
        cleaned_content="Clean body three.",
    )
    batch = ArticleBatch(
        article_ids=[article1.id, article2.id, article3.id],
        grouping_method=GroupingMethod.TITLE_COSINE,
        embedding_model="test-emb",
    )
    summary = BatchSummary(
        batch_id=batch.id,
        model="qwen3.5-flash",
        prompt_version="v1",
        summary="Cohesive summary of three articles.",
        citations=[
            Citation(article_id=article1.id, excerpt="Clean body one."),
            Citation(article_id=article2.id, excerpt="Clean body two."),
            Citation(article_id=article3.id, excerpt="Clean body three."),
        ],
    )
    brief = Brief(
        cadence=Cadence.DAILY,
        covered_start=date.today(),
        covered_end=date.today(),
        content="Daily brief citing the batch.",
        cited_batch_summary_ids=[summary.id],
        cited_article_ids=[article1.id, article2.id, article3.id],
        created_by_run_id=uuid.uuid4(),
    )
    run = WorkflowRun(
        cadence=Cadence.DAILY,
        idempotency_key=f"daily:{date.today().isoformat()}",
        status=WorkflowStatus.SUCCEEDED,
    )

    async with session_scope(session_factory) as sess:
        await upsert_source(sess, source)
        await save_article(sess, article1)
        await save_article(sess, article2)
        await save_article(sess, article3)
        await save_article_batch(sess, batch)
        await save_batch_summary(sess, summary)
        await save_brief(sess, brief)
        await save_workflow_run(sess, run)

    # Idempotency lookup
    async with session_scope(session_factory) as sess:
        found = await get_workflow_run_by_idempotency(sess, run.idempotency_key)
        assert found is not None
        assert found.id == run.id
        assert found.status == WorkflowStatus.SUCCEEDED

    # Brief + citation path
    async with session_scope(session_factory) as sess:
        found_brief = await get_brief_by_cadence_interval(
            sess, Cadence.DAILY, date.today(), date.today()
        )
        assert found_brief is not None
        assert found_brief.id == brief.id
        assert len(found_brief.cited_batch_summary_ids) == 1
        assert len(found_brief.cited_article_ids) == 3


@pytest.mark.asyncio
async def test_checkpoint_roundtrip_via_checkpointer(
    test_settings: Settings,
) -> None:
    # Migrations already applied by previous test in session scope; re-apply is safe
    await _apply_migrations(str(test_settings.database_url))

    async with get_async_checkpointer(test_settings) as cp:
        # Minimal checkpoint put/get using LangGraph checkpoint API
        config = {"configurable": {"thread_id": "test-thread", "checkpoint_ns": ""}}
        # A trivial checkpoint blob (the library serializes)
        checkpoint = {
            "v": 1,
            "ts": "2026-07-10T00:00:00Z",
            "id": "chk-1",
            "channel_values": {},
            "channel_versions": {},
            "versions_seen": {},
        }
        await cp.aput(
            config,  # type: ignore[arg-type]
            checkpoint,  # type: ignore[arg-type]
            {"source": "input"},  # type: ignore[typeddict-item, unused-ignore]
            {},
        )
        loaded = await cp.aget(config)  # type: ignore[arg-type]
        assert loaded is not None
        assert loaded["id"] == "chk-1"
