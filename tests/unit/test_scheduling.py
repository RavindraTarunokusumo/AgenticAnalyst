from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, Mock, call
from uuid import uuid4

import pytest

from analyst_engine.config import ModelProvider, ProcessMode, Settings
from analyst_engine.domain.models import Topic
from analyst_engine.scheduling import register_schedules


def _settings(mode: ProcessMode) -> Settings:
    return Settings(
        app_process_mode=mode,
        model_provider=ModelProvider.OPENROUTER,
        openrouter_api_key="test-key",
        database_url="postgresql+asyncpg://user:password@localhost:5432/analyst_engine",
    )


def _topic(name: str = "Topic") -> Topic:
    now = datetime.now(UTC)
    return Topic(
        id=uuid4(),
        name=name,
        description=f"{name} description",
        keywords=["kw"],
        created_at=now,
        updated_at=now,
    )


def _session_factory() -> Mock:
    return Mock(name="session_factory")


@pytest.mark.asyncio
async def test_register_schedules_skips_registration_in_non_scheduler_mode() -> None:
    scheduler = Mock()
    pipeline = Mock()
    weekly_pipeline = Mock()
    monthly_pipeline = Mock()

    await register_schedules(
        scheduler,
        pipeline,
        weekly_pipeline,
        monthly_pipeline,
        _session_factory(),
        _settings(ProcessMode.API),
    )

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

    topic = _topic("Alpha")
    monkeypatch.setattr(
        "analyst_engine.scheduling.list_topics",
        AsyncMock(return_value=[topic]),
    )
    monkeypatch.setattr(
        "analyst_engine.scheduling.session_scope",
        _fake_session_scope,
    )

    scheduler = Mock()
    pipeline = Mock()
    pipeline.run = AsyncMock()
    weekly_pipeline = Mock()
    weekly_pipeline.run = AsyncMock()
    monthly_pipeline = Mock()
    monthly_pipeline.run = AsyncMock()

    await register_schedules(
        scheduler,
        pipeline,
        weekly_pipeline,
        monthly_pipeline,
        _session_factory(),
        _settings(ProcessMode.SCHEDULER),
    )

    assert scheduler.add_job.call_count == 3
    daily_call = scheduler.add_job.call_args_list[0]
    daily_job_fn = daily_call.args[0]
    assert daily_call.kwargs["id"] == "daily-brief"

    await daily_job_fn()

    pipeline.run.assert_awaited_once_with(fixed_today, topic_id=topic.id)


@pytest.mark.asyncio
async def test_register_schedules_weekly_and_monthly_jobs_use_their_pipelines_with_local_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Weekly/monthly jobs must pass local date.today() explicitly, the same
    anchor the daily job uses - CronTrigger fires on local time, but
    PeriodicBriefPipeline's own default anchor (when none is passed) is a UTC
    clock, so leaving the anchor implicit here would let a cron job compute
    the wrong week/month near local midnight in non-UTC deployments."""
    fixed_today = date(2026, 7, 14)

    class _FixedDate(date):
        @classmethod
        def today(cls) -> "_FixedDate":
            return cls(fixed_today.year, fixed_today.month, fixed_today.day)

    monkeypatch.setattr("analyst_engine.scheduling.date", _FixedDate)

    topic = _topic("Alpha")
    monkeypatch.setattr(
        "analyst_engine.scheduling.list_topics",
        AsyncMock(return_value=[topic]),
    )
    monkeypatch.setattr(
        "analyst_engine.scheduling.session_scope",
        _fake_session_scope,
    )

    scheduler = Mock()
    pipeline = Mock()
    weekly_pipeline = Mock()
    weekly_pipeline.run = AsyncMock()
    monthly_pipeline = Mock()
    monthly_pipeline.run = AsyncMock()

    await register_schedules(
        scheduler,
        pipeline,
        weekly_pipeline,
        monthly_pipeline,
        _session_factory(),
        _settings(ProcessMode.SCHEDULER),
    )

    weekly_call = scheduler.add_job.call_args_list[1]
    monthly_call = scheduler.add_job.call_args_list[2]
    assert weekly_call.kwargs["id"] == "weekly-brief"
    assert monthly_call.kwargs["id"] == "monthly-brief"

    weekly_job_fn = weekly_call.args[0]
    await weekly_job_fn()
    weekly_pipeline.run.assert_awaited_once_with(fixed_today, topic_id=topic.id)

    monthly_job_fn = monthly_call.args[0]
    await monthly_job_fn()
    monthly_pipeline.run.assert_awaited_once_with(fixed_today, topic_id=topic.id)


@pytest.mark.asyncio
async def test_daily_job_runs_pipeline_once_per_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_today = date(2026, 7, 14)

    class _FixedDate(date):
        @classmethod
        def today(cls) -> "_FixedDate":
            return cls(fixed_today.year, fixed_today.month, fixed_today.day)

    monkeypatch.setattr("analyst_engine.scheduling.date", _FixedDate)

    topics = [_topic("Alpha"), _topic("Beta"), _topic("Gamma")]
    monkeypatch.setattr(
        "analyst_engine.scheduling.list_topics",
        AsyncMock(return_value=topics),
    )
    monkeypatch.setattr(
        "analyst_engine.scheduling.session_scope",
        _fake_session_scope,
    )

    scheduler = Mock()
    pipeline = Mock()
    pipeline.run = AsyncMock()
    weekly_pipeline = Mock()
    weekly_pipeline.run = AsyncMock()
    monthly_pipeline = Mock()
    monthly_pipeline.run = AsyncMock()

    await register_schedules(
        scheduler,
        pipeline,
        weekly_pipeline,
        monthly_pipeline,
        _session_factory(),
        _settings(ProcessMode.SCHEDULER),
    )

    daily_job_fn = scheduler.add_job.call_args_list[0].args[0]
    await daily_job_fn()

    assert pipeline.run.await_count == 3
    pipeline.run.assert_has_awaits(
        [
            call(fixed_today, topic_id=topics[0].id),
            call(fixed_today, topic_id=topics[1].id),
            call(fixed_today, topic_id=topics[2].id),
        ]
    )


@pytest.mark.asyncio
async def test_daily_job_continues_after_per_topic_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_today = date(2026, 7, 14)

    class _FixedDate(date):
        @classmethod
        def today(cls) -> "_FixedDate":
            return cls(fixed_today.year, fixed_today.month, fixed_today.day)

    monkeypatch.setattr("analyst_engine.scheduling.date", _FixedDate)

    topics = [_topic("Alpha"), _topic("Beta"), _topic("Gamma")]
    monkeypatch.setattr(
        "analyst_engine.scheduling.list_topics",
        AsyncMock(return_value=topics),
    )
    monkeypatch.setattr(
        "analyst_engine.scheduling.session_scope",
        _fake_session_scope,
    )

    scheduler = Mock()
    pipeline = Mock()

    async def _run_side_effect(target_date: date, *, topic_id: object) -> None:
        if topic_id == topics[1].id:
            raise RuntimeError("topic beta failed")

    pipeline.run = AsyncMock(side_effect=_run_side_effect)
    weekly_pipeline = Mock()
    weekly_pipeline.run = AsyncMock()
    monthly_pipeline = Mock()
    monthly_pipeline.run = AsyncMock()

    await register_schedules(
        scheduler,
        pipeline,
        weekly_pipeline,
        monthly_pipeline,
        _session_factory(),
        _settings(ProcessMode.SCHEDULER),
    )

    daily_job_fn = scheduler.add_job.call_args_list[0].args[0]
    await daily_job_fn()

    assert pipeline.run.await_count == 3
    pipeline.run.assert_has_awaits(
        [
            call(fixed_today, topic_id=topics[0].id),
            call(fixed_today, topic_id=topics[1].id),
            call(fixed_today, topic_id=topics[2].id),
        ]
    )


class _FakeSessionScope:
    """Async context manager that yields a dummy session."""

    def __init__(self, _factory: object) -> None:
        self._session = Mock(name="session")

    async def __aenter__(self) -> Mock:
        return self._session

    async def __aexit__(self, *args: object) -> None:
        return None


def _fake_session_scope(factory: object) -> _FakeSessionScope:
    return _FakeSessionScope(factory)
