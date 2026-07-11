"""Construction and cleanup for process-wide runtime dependencies."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from functools import partial

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from analyst_engine.config import Settings
from analyst_engine.models.factory import create_model_gateway
from analyst_engine.models.gateway import ModelGateway
from analyst_engine.persistence.checkpoints import get_async_checkpointer
from analyst_engine.persistence.engine import get_async_engine, get_session_factory

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
    _closed: bool = field(default=False, init=False, repr=False)

    async def close(self) -> None:
        """Dispose owned resources once, including repeated shutdown requests."""
        if self._closed:
            return
        self._closed = True
        await self.engine.dispose()


def create_runtime(
    settings: Settings,
    *,
    engine_factory: Callable[[Settings], AsyncEngine] = get_async_engine,
    session_factory_builder: Callable[
        [AsyncEngine], async_sessionmaker[AsyncSession]
    ] = get_session_factory,
    gateway_factory: Callable[[Settings], ModelGateway] = create_model_gateway,
    checkpointer_factory_builder: CheckpointerFactoryBuilder = _build_checkpointer_factory,
) -> RuntimeDependencies:
    """Construct the complete dependency bundle from validated settings."""
    engine = engine_factory(settings)
    return RuntimeDependencies(
        settings=settings,
        engine=engine,
        session_factory=session_factory_builder(engine),
        gateway=gateway_factory(settings),
        checkpointer_factory=checkpointer_factory_builder(settings),
    )
