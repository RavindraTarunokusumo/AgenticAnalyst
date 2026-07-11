from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from analyst_engine.api.app import create_app
from analyst_engine.config import ModelProvider, ProcessMode, Settings
from analyst_engine.main import run_scheduler


def _settings(mode: ProcessMode) -> Settings:
    return Settings(
        app_process_mode=mode,
        model_provider=ModelProvider.OPENROUTER,
        openrouter_api_key="test-key",
        database_url="postgresql+asyncpg://user:password@localhost:5432/analyst_engine",
    )


def _runtime(settings: Settings) -> Mock:
    runtime = Mock()
    runtime.settings = settings
    runtime.engine = Mock()
    runtime.session_factory = Mock()
    runtime.gateway = Mock()
    runtime.checkpointer_factory = Mock()
    runtime.close = AsyncMock()
    return runtime


def test_api_mode_uses_complete_runtime_without_registering_schedules() -> None:
    settings = _settings(ProcessMode.API)
    runtime = _runtime(settings)
    runtime_factory = Mock(return_value=runtime)

    app = create_app(
        settings_factory=lambda: settings,
        runtime_factory=runtime_factory,
    )

    with TestClient(app):
        assert app.state.runtime is runtime
        assert app.state.runner.gateway is runtime.gateway
        assert app.state.runner.session_factory is runtime.session_factory
        assert app.state.runner.checkpointer_factory is runtime.checkpointer_factory

    runtime_factory.assert_called_once_with(settings)
    runtime.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduler_mode_registers_once_and_closes_runtime() -> None:
    settings = _settings(ProcessMode.SCHEDULER)
    runtime = _runtime(settings)
    scheduler = Mock()
    register = AsyncMock()
    wait_forever = AsyncMock(return_value=None)

    await run_scheduler(
        settings_factory=lambda: settings,
        runtime_factory=Mock(return_value=runtime),
        scheduler_factory=Mock(return_value=scheduler),
        schedule_registrar=register,
        wait_forever=wait_forever,
    )

    register.assert_awaited_once()
    registered_scheduler, runner, registered_settings = register.await_args.args
    assert registered_scheduler is scheduler
    assert registered_settings is settings
    assert runner.gateway is runtime.gateway
    assert runner.session_factory is runtime.session_factory
    assert runner.checkpointer_factory is runtime.checkpointer_factory
    scheduler.start.assert_called_once_with()
    scheduler.shutdown.assert_called_once_with()
    runtime.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduler_closes_runtime_when_registration_fails() -> None:
    settings = _settings(ProcessMode.SCHEDULER)
    runtime = _runtime(settings)
    scheduler = Mock()
    register = AsyncMock(side_effect=RuntimeError("registration failed"))

    with pytest.raises(RuntimeError, match="registration failed"):
        await run_scheduler(
            settings_factory=lambda: settings,
            runtime_factory=Mock(return_value=runtime),
            scheduler_factory=Mock(return_value=scheduler),
            schedule_registrar=register,
        )

    scheduler.start.assert_not_called()
    scheduler.shutdown.assert_not_called()
    runtime.close.assert_awaited_once()
