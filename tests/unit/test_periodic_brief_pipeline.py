"""Offline unit tests for PeriodicBriefPipeline orchestration."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest

from analyst_engine.domain.models import (
    BatchSummary,
    Brief,
    Cadence,
    Citation,
    WorkflowRun,
    WorkflowStatus,
)
from analyst_engine.pipeline.periodic_brief import PeriodicBriefPipeline

_RUN_ID = UUID("55555555-5555-5555-5555-555555555555")
_BRIEF_ID = UUID("66666666-6666-6666-6666-666666666666")


def _summary(*, summary_id: UUID | None = None) -> BatchSummary:
    article_id = uuid4()
    return BatchSummary(
        id=summary_id or uuid4(),
        batch_id=uuid4(),
        model="qwen3.5-flash",
        prompt_version="v1",
        summary="Periodic summary.",
        citations=[Citation(article_id=article_id, excerpt="Excerpt.")],
    )


class _FakeRunner:
    def __init__(self, workflow_run: WorkflowRun) -> None:
        self.run_weekly = AsyncMock(return_value=workflow_run)
        self.run_monthly = AsyncMock(return_value=workflow_run)


class _PipelineHarness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.candidates: list[BatchSummary] = []
        self.cited_intervals: dict[UUID, tuple[Cadence, date, date]] = {}
        self.existing_workflow_run_by_key: dict[str, WorkflowRun] = {}
        self.brief_by_interval: Brief | None = None
        self.window_calls: list[tuple[date, date]] = []

        @asynccontextmanager
        async def fake_session_scope(_factory: object) -> Any:
            yield object()

        async def fake_list_eligible(
            _session: object, window_start: date, window_end: date
        ) -> list[BatchSummary]:
            self.window_calls.append((window_start, window_end))
            return list(self.candidates)

        async def fake_is_cited(
            _session: object,
            batch_summary_id: UUID,
            cadence: Cadence,
            *,
            exclude_covered_start: date | None = None,
            exclude_covered_end: date | None = None,
        ) -> bool:
            entry = self.cited_intervals.get(batch_summary_id)
            if entry is None:
                return False
            cited_cadence, cited_start, cited_end = entry
            if cited_cadence is not cadence:
                return False
            return (exclude_covered_start, exclude_covered_end) != (cited_start, cited_end)

        async def fake_get_workflow_run_by_idempotency(
            _session: object, idempotency_key: str
        ) -> WorkflowRun | None:
            return self.existing_workflow_run_by_key.get(idempotency_key)

        async def fake_get_brief(
            _session: object, cadence: Cadence, start: date, end: date
        ) -> Brief | None:
            if self.brief_by_interval is None:
                return None
            if (
                self.brief_by_interval.cadence is cadence
                and self.brief_by_interval.covered_start == start
                and self.brief_by_interval.covered_end == end
            ):
                return self.brief_by_interval
            return None

        monkeypatch.setattr(
            "analyst_engine.pipeline.periodic_brief.session_scope", fake_session_scope
        )
        monkeypatch.setattr(
            "analyst_engine.pipeline.periodic_brief.list_eligible_batch_summaries_for_window",
            fake_list_eligible,
        )
        monkeypatch.setattr(
            "analyst_engine.pipeline.periodic_brief.is_batch_summary_cited", fake_is_cited
        )
        monkeypatch.setattr(
            "analyst_engine.pipeline.periodic_brief.get_workflow_run_by_idempotency",
            fake_get_workflow_run_by_idempotency,
        )
        monkeypatch.setattr(
            "analyst_engine.pipeline.periodic_brief.get_brief_by_cadence_interval", fake_get_brief
        )

    def build_pipeline(
        self,
        runner: _FakeRunner,
        *,
        cadence: Cadence,
        clock: datetime,
    ) -> PeriodicBriefPipeline:
        return PeriodicBriefPipeline(
            cadence=cadence,
            session_factory=Mock(),
            runner=runner,  # type: ignore[arg-type]
            clock=lambda: clock,
        )


def test_rejects_non_periodic_cadence() -> None:
    with pytest.raises(ValueError, match="weekly/monthly only"):
        PeriodicBriefPipeline(
            cadence=Cadence.DAILY,
            session_factory=Mock(),
            runner=Mock(),
        )


@pytest.mark.asyncio
async def test_weekly_window_normalizes_mid_week_anchor_to_monday_sunday(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _PipelineHarness(monkeypatch)
    workflow_run = WorkflowRun(
        id=_RUN_ID,
        cadence=Cadence.WEEKLY,
        idempotency_key="weekly:2026-07-13:2026-07-19",
        status=WorkflowStatus.SUCCEEDED,
    )
    runner = _FakeRunner(workflow_run)
    pipeline = harness.build_pipeline(
        runner, cadence=Cadence.WEEKLY, clock=datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    )
    harness.candidates = [_summary()]

    result = await pipeline.run()

    # 2026-07-16 is a Thursday; the containing week is Mon 2026-07-13 - Sun 2026-07-19.
    assert result.covered_start == date(2026, 7, 13)
    assert result.covered_end == date(2026, 7, 19)
    runner.run_weekly.assert_awaited_once()
    await_args = runner.run_weekly.await_args
    assert await_args is not None
    assert await_args.args[0] == date(2026, 7, 13)
    assert len(await_args.kwargs["batch_summaries"]) == 1


@pytest.mark.asyncio
async def test_monthly_window_normalizes_mid_month_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _PipelineHarness(monkeypatch)
    workflow_run = WorkflowRun(
        id=_RUN_ID,
        cadence=Cadence.MONTHLY,
        idempotency_key="monthly:2026-07-01:2026-07-31",
        status=WorkflowStatus.SUCCEEDED,
    )
    runner = _FakeRunner(workflow_run)
    pipeline = harness.build_pipeline(
        runner, cadence=Cadence.MONTHLY, clock=datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    )
    harness.candidates = [_summary()]

    result = await pipeline.run()

    assert result.covered_start == date(2026, 7, 1)
    assert result.covered_end == date(2026, 7, 31)
    await_args = runner.run_monthly.await_args
    assert await_args is not None
    assert await_args.args[0] == date(2026, 7, 1)


@pytest.mark.asyncio
async def test_monthly_window_handles_december_year_rollover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _PipelineHarness(monkeypatch)
    workflow_run = WorkflowRun(
        id=_RUN_ID,
        cadence=Cadence.MONTHLY,
        idempotency_key="monthly:2026-12-01:2026-12-31",
        status=WorkflowStatus.SUCCEEDED,
    )
    runner = _FakeRunner(workflow_run)
    pipeline = harness.build_pipeline(
        runner, cadence=Cadence.MONTHLY, clock=datetime(2026, 12, 20, 12, 0, tzinfo=UTC)
    )
    harness.candidates = [_summary()]

    result = await pipeline.run()

    assert result.covered_start == date(2026, 12, 1)
    assert result.covered_end == date(2026, 12, 31)


@pytest.mark.asyncio
async def test_no_content_short_circuits_without_calling_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _PipelineHarness(monkeypatch)
    runner = _FakeRunner(
        WorkflowRun(
            cadence=Cadence.WEEKLY,
            idempotency_key="weekly:2026-07-13:2026-07-19",
            status=WorkflowStatus.SUCCEEDED,
        )
    )
    pipeline = harness.build_pipeline(
        runner, cadence=Cadence.WEEKLY, clock=datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    )
    harness.candidates = []

    result = await pipeline.run()

    assert result.is_no_content is True
    assert result.summaries_selected == 0
    assert result.workflow_run_id is None
    runner.run_weekly.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_prior_run_retry_still_calls_runner_with_no_new_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _PipelineHarness(monkeypatch)
    idempotency_key = "weekly:2026-07-13:2026-07-19"
    existing_run = WorkflowRun(
        id=_RUN_ID,
        cadence=Cadence.WEEKLY,
        idempotency_key=idempotency_key,
        status=WorkflowStatus.SUCCEEDED,
    )
    harness.existing_workflow_run_by_key[idempotency_key] = existing_run
    harness.brief_by_interval = Brief(
        id=_BRIEF_ID,
        cadence=Cadence.WEEKLY,
        covered_start=date(2026, 7, 13),
        covered_end=date(2026, 7, 19),
        content="Weekly brief.",
        cited_batch_summary_ids=[uuid4()],
        cited_article_ids=[uuid4()],
        created_by_run_id=_RUN_ID,
    )
    runner = _FakeRunner(existing_run)
    pipeline = harness.build_pipeline(
        runner, cadence=Cadence.WEEKLY, clock=datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    )
    harness.candidates = []

    result = await pipeline.run()

    assert result.is_no_content is False
    assert result.workflow_run_id == _RUN_ID
    assert result.brief_id == _BRIEF_ID
    runner.run_weekly.assert_awaited_once()


@pytest.mark.asyncio
async def test_already_cited_for_this_cadence_is_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _PipelineHarness(monkeypatch)
    summary = _summary()
    harness.candidates = [summary]
    harness.cited_intervals[summary.id] = (
        Cadence.WEEKLY,
        date(2026, 7, 6),
        date(2026, 7, 12),
    )
    runner = _FakeRunner(
        WorkflowRun(
            cadence=Cadence.WEEKLY,
            idempotency_key="weekly:2026-07-13:2026-07-19",
            status=WorkflowStatus.SUCCEEDED,
        )
    )
    pipeline = harness.build_pipeline(
        runner, cadence=Cadence.WEEKLY, clock=datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    )

    result = await pipeline.run()

    assert result.is_no_content is True
    assert result.summaries_selected == 0
    runner.run_weekly.assert_not_called()


@pytest.mark.asyncio
async def test_cited_for_different_cadence_is_not_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A summary already cited by a Daily brief is still independently
    eligible for that week's Weekly brief - cadence-independent citation
    tracking (spec success criterion 4)."""
    harness = _PipelineHarness(monkeypatch)
    summary = _summary()
    harness.candidates = [summary]
    harness.cited_intervals[summary.id] = (
        Cadence.DAILY,
        date(2026, 7, 14),
        date(2026, 7, 14),
    )
    workflow_run = WorkflowRun(
        id=_RUN_ID,
        cadence=Cadence.WEEKLY,
        idempotency_key="weekly:2026-07-13:2026-07-19",
        status=WorkflowStatus.SUCCEEDED,
    )
    runner = _FakeRunner(workflow_run)
    pipeline = harness.build_pipeline(
        runner, cadence=Cadence.WEEKLY, clock=datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    )
    harness.brief_by_interval = Brief(
        id=_BRIEF_ID,
        cadence=Cadence.WEEKLY,
        covered_start=date(2026, 7, 13),
        covered_end=date(2026, 7, 19),
        content="Weekly brief.",
        cited_batch_summary_ids=[summary.id],
        cited_article_ids=[],
        created_by_run_id=_RUN_ID,
    )

    result = await pipeline.run()

    assert result.is_no_content is False
    assert result.summaries_selected == 1
    runner.run_weekly.assert_awaited_once()
    assert result.brief_id == _BRIEF_ID
