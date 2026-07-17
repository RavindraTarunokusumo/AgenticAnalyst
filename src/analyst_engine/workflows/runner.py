"""Durable orchestration for checkpointed cadence workflows."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, suppress
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from analyst_engine.config import Settings
from analyst_engine.domain.models import (
    BatchSummary,
    Brief,
    Cadence,
    NarrativeStateVersion,
    WorkflowRun,
    WorkflowStatus,
)
from analyst_engine.models.gateway import ModelError, ModelGateway
from analyst_engine.persistence.engine import session_scope
from analyst_engine.persistence.repositories import (
    WorkflowRunAlreadyExistsError,
    claim_pending_workflow_run,
    create_workflow_run,
    get_narrative_version_as_of,
    get_workflow_run_by_idempotency,
    list_prior_briefs,
    update_workflow_run,
)
from analyst_engine.workflows.graphs import (
    build_daily_graph,
    build_monthly_graph,
    build_weekly_graph,
)

CheckpointerFactory = Callable[[], AbstractAsyncContextManager[BaseCheckpointSaver[Any]]]
GraphBuilder = Callable[[ModelGateway, async_sessionmaker[AsyncSession]], Any]

GRAPH_BUILDERS: dict[Cadence, GraphBuilder] = {
    Cadence.DAILY: build_daily_graph,
    Cadence.WEEKLY: build_weekly_graph,
    Cadence.MONTHLY: build_monthly_graph,
}

_TERMINAL_STATUSES = frozenset(
    {WorkflowStatus.SUCCEEDED, WorkflowStatus.FAILED, WorkflowStatus.RESUMABLE}
)


class WorkflowRunner:
    def __init__(
        self,
        settings: Settings,
        gateway: ModelGateway,
        session_factory: async_sessionmaker[AsyncSession],
        checkpointer_factory: CheckpointerFactory,
    ) -> None:
        self.settings = settings
        self.gateway = gateway
        self.session_factory = session_factory
        self.checkpointer_factory = checkpointer_factory

    async def _ensure_run(
        self, cadence: Cadence, topic_id: UUID, start: date, end: date
    ) -> WorkflowRun:
        key = f"{cadence.value}:{topic_id}:{start.isoformat()}:{end.isoformat()}"
        try:
            async with session_scope(self.session_factory) as session:
                existing = await get_workflow_run_by_idempotency(session, key)
                if existing is not None:
                    return existing
                run = WorkflowRun(cadence=cadence, idempotency_key=key)
                return await create_workflow_run(session, run)
        except WorkflowRunAlreadyExistsError:
            # A concurrent trigger may win the unique-key race. The failed
            # transaction must exit before the winner is read in a new one.
            pass

        async with session_scope(self.session_factory) as session:
            existing = await get_workflow_run_by_idempotency(session, key)
            if existing is None:
                raise RuntimeError("workflow run creation conflicted but no durable run exists")
            return existing

    async def _update_run(self, run: WorkflowRun) -> WorkflowRun:
        async with session_scope(self.session_factory) as session:
            return await update_workflow_run(session, run)

    async def _claim_run(self, run: WorkflowRun) -> WorkflowRun | None:
        candidate = run.model_copy(update={"checkpoint_ref": str(run.id)})
        async with session_scope(self.session_factory) as session:
            return await claim_pending_workflow_run(session, candidate)

    async def _load_context(
        self, cadence: Cadence, topic_id: UUID, start: date
    ) -> tuple[NarrativeStateVersion | None, list[Brief]]:
        prior_cadence = {
            Cadence.DAILY: Cadence.DAILY,
            Cadence.WEEKLY: Cadence.DAILY,
            Cadence.MONTHLY: Cadence.WEEKLY,
        }[cadence]
        async with session_scope(self.session_factory) as session:
            return (
                await get_narrative_version_as_of(session, start, topic_id=topic_id),
                await list_prior_briefs(session, prior_cadence, start, topic_id=topic_id),
            )

    @staticmethod
    def _failure_summary(error: Exception) -> str:
        if isinstance(error, ModelError):
            return f"{type(error).__name__}: provider operation failed"
        return f"{type(error).__name__}: workflow execution failed"

    async def _execute(
        self,
        cadence: Cadence,
        topic_id: UUID,
        start: date,
        end: date,
        batch_summaries: list[BatchSummary] | None,
    ) -> WorkflowRun:
        run = await self._ensure_run(cadence, topic_id, start, end)
        if run.status in _TERMINAL_STATUSES:
            return run
        if run.status is WorkflowStatus.RUNNING:
            return run
        running = await self._claim_run(run)
        if running is None:
            async with session_scope(self.session_factory) as session:
                claimed_elsewhere = await get_workflow_run_by_idempotency(
                    session, run.idempotency_key
                )
            if claimed_elsewhere is None:
                raise RuntimeError("workflow run claim lost without a durable run")
            return claimed_elsewhere

        try:
            current_narrative, prior_briefs = await self._load_context(cadence, topic_id, start)
            state = {
                "run_id": str(run.id),
                "cadence": cadence.value,
                "topic_id": str(topic_id),
                "covered_start": start.isoformat(),
                "covered_end": end.isoformat(),
                "idempotency_key": run.idempotency_key,
                "batch_summaries": [
                    summary.model_dump(mode="python") for summary in batch_summaries or []
                ],
                "prior_briefs": [brief.model_dump(mode="python") for brief in prior_briefs],
                "current_narrative": (
                    current_narrative.model_dump(mode="python")
                    if current_narrative is not None
                    else None
                ),
                "correlation_id": str(run.id),
            }
            config = {
                "configurable": {
                    "thread_id": str(run.id),
                    "checkpoint_ns": f"{cadence.value}:{topic_id}",
                }
            }
            builder = GRAPH_BUILDERS[cadence](self.gateway, self.session_factory)
            async with self.checkpointer_factory() as checkpointer:
                graph = builder.compile(checkpointer=checkpointer)
                await graph.ainvoke(state, config=config)
            succeeded = running.model_copy(
                update={
                    "status": WorkflowStatus.SUCCEEDED,
                    "error_summary": None,
                    "completed_at": datetime.now(UTC),
                }
            )
            return await self._update_run(succeeded)
        except Exception as error:
            failed = running.model_copy(
                update={
                    "status": WorkflowStatus.FAILED,
                    "error_summary": self._failure_summary(error),
                    "completed_at": datetime.now(UTC),
                }
            )
            with suppress(Exception):
                await self._update_run(failed)
            raise

    async def run_daily(
        self,
        target_date: date | None = None,
        *,
        topic_id: UUID,
        batch_summaries: list[BatchSummary] | None = None,
    ) -> WorkflowRun:
        target = target_date or date.today()
        return await self._execute(Cadence.DAILY, topic_id, target, target, batch_summaries)

    async def run_weekly(
        self,
        target_date: date | None = None,
        *,
        topic_id: UUID,
        batch_summaries: list[BatchSummary] | None = None,
    ) -> WorkflowRun:
        today = date.today()
        start = target_date or (today - timedelta(days=today.weekday()))
        return await self._execute(
            Cadence.WEEKLY, topic_id, start, start + timedelta(days=6), batch_summaries
        )

    async def run_monthly(
        self,
        target_date: date | None = None,
        *,
        topic_id: UUID,
        batch_summaries: list[BatchSummary] | None = None,
    ) -> WorkflowRun:
        start = target_date or date.today().replace(day=1)
        next_month = (
            start.replace(year=start.year + 1, month=1, day=1)
            if start.month == 12
            else start.replace(month=start.month + 1, day=1)
        )
        return await self._execute(
            Cadence.MONTHLY,
            topic_id,
            start,
            next_month - timedelta(days=1),
            batch_summaries,
        )
