"""Construction and cleanup for process-wide runtime dependencies."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from functools import partial

import httpx
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from analyst_engine.config import Settings
from analyst_engine.domain.models import Cadence
from analyst_engine.ingestion.extractor import Crawl4AIExtractor, PrimaryHttpExtractor
from analyst_engine.ingestion.feed_client import FeedClient
from analyst_engine.ingestion.file_extractor import (
    FileExtractor,
    PdfFileExtractor,
    TextFileExtractor,
)
from analyst_engine.ingestion.service import IngestionService
from analyst_engine.models.factory import create_model_gateway
from analyst_engine.models.gateway import ModelGateway
from analyst_engine.persistence.checkpoints import get_async_checkpointer
from analyst_engine.persistence.engine import get_async_engine, get_session_factory
from analyst_engine.pipeline.daily_brief import DailyBriefPipeline
from analyst_engine.pipeline.periodic_brief import PeriodicBriefPipeline
from analyst_engine.topics.matcher import matches
from analyst_engine.workflows.runner import WorkflowRunner

CheckpointerFactory = Callable[[], AbstractAsyncContextManager[AsyncPostgresSaver]]
CheckpointerFactoryBuilder = Callable[[Settings], CheckpointerFactory]


def _build_checkpointer_factory(settings: Settings) -> CheckpointerFactory:
    return partial(get_async_checkpointer, settings)


@dataclass(slots=True)
class RuntimeDependencies:
    """Small typed bundle of dependencies owned by one application process."""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    gateway: ModelGateway
    checkpointer_factory: CheckpointerFactory
    http_client: httpx.AsyncClient
    _closed: bool = field(default=False, init=False, repr=False)

    async def close(self) -> None:
        """Dispose owned resources once, including repeated shutdown requests."""
        if self._closed:
            return
        await self.http_client.aclose()
        await self.engine.dispose()
        self._closed = True


def build_ingestion_service(runtime: RuntimeDependencies) -> IngestionService:
    """Construct the IngestionService shared by API and scheduler processes."""
    feed_client = FeedClient(
        runtime.http_client,
        timeout_seconds=runtime.settings.feed_request_timeout_seconds,
        size_limit_bytes=runtime.settings.feed_response_size_limit_bytes,
        user_agent=runtime.settings.feed_user_agent,
    )
    primary_extractor = PrimaryHttpExtractor(
        runtime.http_client,
        timeout_seconds=runtime.settings.feed_request_timeout_seconds,
        size_limit_bytes=runtime.settings.article_max_response_size_bytes,
        user_agent=runtime.settings.feed_user_agent,
    )
    fallback_extractor = Crawl4AIExtractor(
        timeout_seconds=runtime.settings.feed_request_timeout_seconds,
    )
    file_extractors: dict[str, FileExtractor] = {
        "application/pdf": PdfFileExtractor(),
        "text/plain": TextFileExtractor(),
    }
    return IngestionService(
        session_factory=runtime.session_factory,
        feed_client=feed_client,
        primary_extractor=primary_extractor,
        fallback_extractor=fallback_extractor,
        settings=runtime.settings,
        file_extractors=file_extractors,
        is_relevant=matches,
    )


def build_daily_brief_pipeline(
    runtime: RuntimeDependencies,
    *,
    ingestion_service: IngestionService,
    runner: WorkflowRunner,
) -> DailyBriefPipeline:
    """Construct the DailyBriefPipeline shared by API and scheduler processes."""
    return DailyBriefPipeline(
        session_factory=runtime.session_factory,
        ingestion_service=ingestion_service,
        runner=runner,
        gateway=runtime.gateway,
        settings=runtime.settings,
    )


def build_periodic_brief_pipeline(
    runtime: RuntimeDependencies,
    *,
    runner: WorkflowRunner,
    cadence: Cadence,
) -> PeriodicBriefPipeline:
    """Construct a PeriodicBriefPipeline shared by API and scheduler processes."""
    return PeriodicBriefPipeline(
        cadence=cadence,
        session_factory=runtime.session_factory,
        runner=runner,
    )


async def create_runtime(
    settings: Settings,
    *,
    engine_factory: Callable[[Settings], AsyncEngine] = get_async_engine,
    session_factory_builder: Callable[
        [AsyncEngine], async_sessionmaker[AsyncSession]
    ] = get_session_factory,
    gateway_factory: Callable[[Settings], ModelGateway] = create_model_gateway,
    checkpointer_factory_builder: CheckpointerFactoryBuilder = _build_checkpointer_factory,
    http_client_factory: Callable[[Settings], httpx.AsyncClient] = lambda _settings: (
        httpx.AsyncClient()
    ),
) -> RuntimeDependencies:
    """Construct the complete dependency bundle from validated settings."""
    engine = engine_factory(settings)
    http_client: httpx.AsyncClient | None = None
    try:
        http_client = http_client_factory(settings)
        return RuntimeDependencies(
            settings=settings,
            engine=engine,
            session_factory=session_factory_builder(engine),
            gateway=gateway_factory(settings),
            checkpointer_factory=checkpointer_factory_builder(settings),
            http_client=http_client,
        )
    except Exception:
        if http_client is not None:
            await http_client.aclose()
        await engine.dispose()
        raise
