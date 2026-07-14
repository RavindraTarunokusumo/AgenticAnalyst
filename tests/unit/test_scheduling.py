from datetime import date
from unittest.mock import AsyncMock, Mock

import pytest

from analyst_engine.config import ModelProvider, ProcessMode, Settings
from analyst_engine.scheduling import register_schedules


def _settings(mode: ProcessMode) -> Settings:
    return Settings(
        app_process_mode=mode,
        model_provider=ModelProvider.OPENROUTER,
        openrouter_api_key="test-key",
        database_url="postgresql+asyncpg://user:password@localhost:5432/analyst_engine",
    )


@pytest.mark.asyncio
async def test_register_schedules_skips_registration_in_non_scheduler_mode() -> None:
    scheduler = Mock()
    runner = Mock()
    pipeline = Mock()

    await register_schedules(scheduler, runner, pipeline, _settings(ProcessMode.API))

    scheduler.add_job.assert_not_called()


@pytest.mark.asyncio
async def test_register_schedules_daily_job_invokes_pipeline_run_with_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_today = date(2026, 7, 14)

    class _FixedDate(date):
        @classmethod
        def today(cls) -> "_FixedDate":
            return cls(fixed_today.year, fixed_today.month, fixed_today.day)

    monkeypatch.setattr("analyst_engine.scheduling.date", _FixedDate)

    scheduler = Mock()
    runner = Mock()
    runner.run_weekly = Mock()
    runner.run_monthly = Mock()
    pipeline = Mock()
    pipeline.run = AsyncMock()

    await register_schedules(scheduler, runner, pipeline, _settings(ProcessMode.SCHEDULER))

    assert scheduler.add_job.call_count == 3
    daily_call = scheduler.add_job.call_args_list[0]
    daily_job_fn = daily_call.args[0]
    assert daily_call.kwargs["id"] == "daily-brief"

    await daily_job_fn()

    pipeline.run.assert_awaited_once_with(fixed_today)


@pytest.mark.asyncio
async def test_register_schedules_weekly_and_monthly_jobs_use_runner() -> None:
    scheduler = Mock()
    runner = Mock()
    runner.run_weekly = Mock()
    runner.run_monthly = Mock()
    pipeline = Mock()

    await register_schedules(scheduler, runner, pipeline, _settings(ProcessMode.SCHEDULER))

    weekly_call = scheduler.add_job.call_args_list[1]
    monthly_call = scheduler.add_job.call_args_list[2]

    assert weekly_call.args[0] is runner.run_weekly
    assert weekly_call.kwargs["id"] == "weekly-brief"
    assert monthly_call.args[0] is runner.run_monthly
    assert monthly_call.kwargs["id"] == "monthly-brief"
