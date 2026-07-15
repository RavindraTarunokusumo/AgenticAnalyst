"""Weekly/monthly brief pipeline selecting real batch-summary evidence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from analyst_engine.domain.models import BatchSummary, Cadence, WorkflowRun, WorkflowStatus
from analyst_engine.persistence.engine import session_scope
from analyst_engine.persistence.repositories import (
    get_brief_by_cadence_interval,
    get_workflow_run_by_idempotency,
    is_batch_summary_cited,
    list_eligible_batch_summaries_for_window,
)
from analyst_engine.workflows.runner import WorkflowRunner


@dataclass(frozen=True)
class PeriodicPipelineResult:
    cadence: Cadence
    covered_start: date
    covered_end: date
    summaries_selected: int
    is_no_content: bool
    workflow_run_id: UUID | None
    workflow_status: WorkflowStatus | None
    brief_id: UUID | None


def _week_window(anchor: date) -> tuple[date, date]:
    start = anchor - timedelta(days=anchor.weekday())
    return start, start + timedelta(days=6)


def _month_window(anchor: date) -> tuple[date, date]:
    start = anchor.replace(day=1)
    next_month = (
        start.replace(year=start.year + 1, month=1, day=1)
        if start.month == 12
        else start.replace(month=start.month + 1, day=1)
    )
    return start, next_month - timedelta(days=1)


class PeriodicBriefPipeline:
    def __init__(
        self,
        *,
        cadence: Cadence,
        session_factory: async_sessionmaker[AsyncSession],
        runner: WorkflowRunner,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if cadence not in (Cadence.WEEKLY, Cadence.MONTHLY):
            raise ValueError(f"PeriodicBriefPipeline supports weekly/monthly only, got {cadence}")
        self._cadence = cadence
        self._session_factory = session_factory
        self._runner = runner
        self._clock = clock

    async def run(self, anchor_date: date | None = None) -> PeriodicPipelineResult:
        anchor = anchor_date or self._clock().date()
        window_start, window_end = (
            _week_window(anchor) if self._cadence is Cadence.WEEKLY else _month_window(anchor)
        )

        async with session_scope(self._session_factory) as session:
            candidates = await list_eligible_batch_summaries_for_window(
                session, window_start, window_end
            )

        selected: list[BatchSummary] = []
        for candidate in candidates:
            async with session_scope(self._session_factory) as session:
                already_cited = await is_batch_summary_cited(
                    session,
                    candidate.id,
                    self._cadence,
                    exclude_covered_start=window_start,
                    exclude_covered_end=window_end,
                )
            if already_cited:
                continue
            selected.append(candidate)

        if not selected:
            # A candidate summary already cited by this exact cadence+window
            # (a retry after a prior success) naturally yields zero
            # selections, distinct from a genuine no-content window that has
            # never had a WorkflowRun. Let a terminal prior run fall through
            # to the runner so its own idempotency-key lookup returns it
            # directly, mirroring DailyBriefPipeline's exact pattern.
            idempotency_key = (
                f"{self._cadence.value}:{window_start.isoformat()}:{window_end.isoformat()}"
            )
            async with session_scope(self._session_factory) as session:
                existing_run = await get_workflow_run_by_idempotency(session, idempotency_key)
            if existing_run is None or existing_run.status not in (
                WorkflowStatus.SUCCEEDED,
                WorkflowStatus.FAILED,
            ):
                return PeriodicPipelineResult(
                    cadence=self._cadence,
                    covered_start=window_start,
                    covered_end=window_end,
                    summaries_selected=0,
                    is_no_content=True,
                    workflow_run_id=None,
                    workflow_status=None,
                    brief_id=None,
                )

        workflow_run: WorkflowRun
        if self._cadence is Cadence.WEEKLY:
            workflow_run = await self._runner.run_weekly(window_start, batch_summaries=selected)
        else:
            workflow_run = await self._runner.run_monthly(window_start, batch_summaries=selected)

        brief_id: UUID | None = None
        if workflow_run.status is WorkflowStatus.SUCCEEDED:
            async with session_scope(self._session_factory) as session:
                brief = await get_brief_by_cadence_interval(
                    session, self._cadence, window_start, window_end
                )
                brief_id = brief.id if brief is not None else None

        return PeriodicPipelineResult(
            cadence=self._cadence,
            covered_start=window_start,
            covered_end=window_end,
            summaries_selected=len(selected),
            is_no_content=False,
            workflow_run_id=workflow_run.id,
            workflow_status=workflow_run.status,
            brief_id=brief_id,
        )
