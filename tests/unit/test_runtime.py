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


def _http_client_mock() -> Mock:
    client = Mock()
    client.aclose = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_create_runtime_constructs_complete_dependency_bundle() -> None:
    settings = _settings()
    engine = Mock()
    session_factory = Mock()
    gateway = Mock()
    http_client = _http_client_mock()

    @asynccontextmanager
    async def checkpointer_factory():
        yield Mock()

    engine_factory = Mock(return_value=engine)
    session_factory_builder = Mock(return_value=session_factory)
    gateway_factory = Mock(return_value=gateway)
    http_client_factory = Mock(return_value=http_client)

    runtime = await create_runtime(
        settings,
        engine_factory=engine_factory,
        session_factory_builder=session_factory_builder,
        gateway_factory=gateway_factory,
        checkpointer_factory_builder=lambda _settings: checkpointer_factory,
        http_client_factory=http_client_factory,
    )

    assert runtime.settings is settings
    assert runtime.engine is engine
    assert runtime.session_factory is session_factory
    assert runtime.gateway is gateway
    assert runtime.checkpointer_factory is checkpointer_factory
    assert runtime.http_client is http_client
    engine_factory.assert_called_once_with(settings)
    session_factory_builder.assert_called_once_with(engine)
    gateway_factory.assert_called_once_with(settings)
    http_client_factory.assert_called_once_with(settings)


@pytest.mark.asyncio
async def test_create_runtime_disposes_engine_when_dependency_construction_fails() -> None:
    engine = Mock()
    engine.dispose = AsyncMock()
    http_client = _http_client_mock()

    with pytest.raises(RuntimeError, match="gateway failed"):
        await create_runtime(
            _settings(),
            engine_factory=Mock(return_value=engine),
            session_factory_builder=Mock(return_value=Mock()),
            gateway_factory=Mock(side_effect=RuntimeError("gateway failed")),
            http_client_factory=Mock(return_value=http_client),
        )

    engine.dispose.assert_awaited_once()
    http_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_runtime_closes_http_client_when_dependency_construction_fails() -> None:
    engine = Mock()
    engine.dispose = AsyncMock()
    http_client = _http_client_mock()

    with pytest.raises(RuntimeError, match="session factory failed"):
        await create_runtime(
            _settings(),
            engine_factory=Mock(return_value=engine),
            session_factory_builder=Mock(side_effect=RuntimeError("session factory failed")),
            gateway_factory=Mock(return_value=Mock()),
            http_client_factory=Mock(return_value=http_client),
        )

    http_client.aclose.assert_awaited_once()
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_close_disposes_owned_engine_once() -> None:
    engine = Mock()
    engine.dispose = AsyncMock()
    http_client = _http_client_mock()
    runtime = RuntimeDependencies(
        settings=_settings(),
        engine=engine,
        session_factory=Mock(),
        gateway=Mock(),
        checkpointer_factory=Mock(),
        http_client=http_client,
    )

    await runtime.close()
    await runtime.close()

    engine.dispose.assert_awaited_once()
    http_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_close_can_retry_after_disposal_fails() -> None:
    engine = Mock()
    engine.dispose = AsyncMock(side_effect=[RuntimeError("dispose failed"), None])
    http_client = _http_client_mock()
    runtime = RuntimeDependencies(
        settings=_settings(),
        engine=engine,
        session_factory=Mock(),
        gateway=Mock(),
        checkpointer_factory=Mock(),
        http_client=http_client,
    )

    with pytest.raises(RuntimeError, match="dispose failed"):
        await runtime.close()
    await runtime.close()

    assert engine.dispose.await_count == 2
    # http_client.aclose() runs before the fallible engine.dispose() in close(),
    # so a retry after engine.dispose() fails re-invokes aclose() too - real
    # httpx.AsyncClient.aclose() is safe to call more than once.
    assert http_client.aclose.await_count == 2
