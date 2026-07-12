from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest

from analyst_engine.config import ModelProvider, Settings
from analyst_engine.runtime import RuntimeDependencies, create_runtime


def _settings() -> Settings:
    return Settings(
        model_provider=ModelProvider.OPENROUTER,
        openrouter_api_key="test-key",
        database_url="postgresql+asyncpg://user:password@localhost:5432/analyst_engine",
    )


@pytest.mark.asyncio
async def test_create_runtime_constructs_complete_dependency_bundle() -> None:
    settings = _settings()
    engine = Mock()
    session_factory = Mock()
    gateway = Mock()

    @asynccontextmanager
    async def checkpointer_factory():
        yield Mock()

    engine_factory = Mock(return_value=engine)
    session_factory_builder = Mock(return_value=session_factory)
    gateway_factory = Mock(return_value=gateway)

    runtime = await create_runtime(
        settings,
        engine_factory=engine_factory,
        session_factory_builder=session_factory_builder,
        gateway_factory=gateway_factory,
        checkpointer_factory_builder=lambda _settings: checkpointer_factory,
    )

    assert runtime.settings is settings
    assert runtime.engine is engine
    assert runtime.session_factory is session_factory
    assert runtime.gateway is gateway
    assert runtime.checkpointer_factory is checkpointer_factory
    engine_factory.assert_called_once_with(settings)
    session_factory_builder.assert_called_once_with(engine)
    gateway_factory.assert_called_once_with(settings)


@pytest.mark.asyncio
async def test_create_runtime_disposes_engine_when_dependency_construction_fails() -> None:
    engine = Mock()
    engine.dispose = AsyncMock()

    with pytest.raises(RuntimeError, match="gateway failed"):
        await create_runtime(
            _settings(),
            engine_factory=Mock(return_value=engine),
            session_factory_builder=Mock(return_value=Mock()),
            gateway_factory=Mock(side_effect=RuntimeError("gateway failed")),
        )

    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_close_disposes_owned_engine_once() -> None:
    engine = Mock()
    engine.dispose = AsyncMock()
    runtime = RuntimeDependencies(
        settings=_settings(),
        engine=engine,
        session_factory=Mock(),
        gateway=Mock(),
        checkpointer_factory=Mock(),
    )

    await runtime.close()
    await runtime.close()

    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_close_can_retry_after_disposal_fails() -> None:
    engine = Mock()
    engine.dispose = AsyncMock(side_effect=[RuntimeError("dispose failed"), None])
    runtime = RuntimeDependencies(
        settings=_settings(),
        engine=engine,
        session_factory=Mock(),
        gateway=Mock(),
        checkpointer_factory=Mock(),
    )

    with pytest.raises(RuntimeError, match="dispose failed"):
        await runtime.close()
    await runtime.close()

    assert engine.dispose.await_count == 2
