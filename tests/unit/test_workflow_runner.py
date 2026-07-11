from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

from analyst_engine.domain.models import (
    BatchSummary,
    Cadence,
    Citation,
    WorkflowRun,
    WorkflowStatus,
)
from analyst_engine.models.gateway import RetryableModelError
from analyst_engine.workflows.runner import WorkflowRunner


def _summary() -> BatchSummary:
    return BatchSummary(
        batch_id=UUID("00000000-0000-0000-0000-000000000010"),
        model="fake",
        prompt_version="v1",
        summary="summary",
        citations=[Citation(article_id=UUID("00000000-0000-0000-0000-000000000011"))],
        created_at=datetime(2026, 7, 12, tzinfo=UTC),
    )


class _SessionScope:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_args: object) -> None:
        return None


class _CompiledGraph:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def ainvoke(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((state, config))
        if self.error is not None:
            raise self.error
        return state | {"brief": {"content": "done"}}


class _GraphBuilder:
    def __init__(self, compiled: _CompiledGraph) -> None:
        self.compiled = compiled
        self.checkpointers: list[object] = []

    def compile(self, *, checkpointer: object) -> _CompiledGraph:
        self.checkpointers.append(checkpointer)
        return self.compiled


def _runner() -> WorkflowRunner:
    @asynccontextmanager
    async def checkpointer_factory():
        yield "postgres-checkpointer"

    return WorkflowRunner(Mock(), Mock(), Mock(), checkpointer_factory)


@pytest.mark.parametrize(
    ("method", "target", "cadence", "start", "end"),
    [
        ("run_daily", date(2026, 7, 12), Cadence.DAILY, date(2026, 7, 12), date(2026, 7, 12)),
        ("run_weekly", date(2026, 7, 6), Cadence.WEEKLY, date(2026, 7, 6), date(2026, 7, 12)),
        ("run_monthly", date(2026, 2, 1), Cadence.MONTHLY, date(2026, 2, 1), date(2026, 2, 28)),
    ],
)
async def test_cadences_invoke_selected_checkpointed_graph_with_stable_identity(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    target: date,
    cadence: Cadence,
    start: date,
    end: date,
) -> None:
    runner = _runner()
    run_id = UUID("00000000-0000-0000-0000-000000000001")
    pending = WorkflowRun(
        id=run_id,
        cadence=cadence,
        idempotency_key=f"{cadence.value}:{start.isoformat()}:{end.isoformat()}",
    )
    running = pending.model_copy(
        update={"status": WorkflowStatus.RUNNING, "checkpoint_ref": str(run_id)}
    )
    succeeded = running.model_copy(update={"status": WorkflowStatus.SUCCEEDED})
    compiled = _CompiledGraph()
    selected = _GraphBuilder(compiled)
    other = Mock()

    monkeypatch.setattr(runner, "_ensure_run", AsyncMock(return_value=pending))
    monkeypatch.setattr(runner, "_update_run", AsyncMock(side_effect=[running, succeeded]))
    monkeypatch.setattr(
        "analyst_engine.workflows.runner.GRAPH_BUILDERS",
        {Cadence.DAILY: other, Cadence.WEEKLY: other, Cadence.MONTHLY: other}
        | {cadence: Mock(return_value=selected)},
    )

    result = await getattr(runner, method)(target, batch_summaries=[_summary()])

    assert result.status is WorkflowStatus.SUCCEEDED
    assert selected.checkpointers == ["postgres-checkpointer"]
    state, config = compiled.calls[0]
    assert state["run_id"] == str(run_id)
    assert state["correlation_id"] == str(run_id)
    assert state["cadence"] == cadence.value
    assert config == {"configurable": {"thread_id": str(run_id), "checkpoint_ns": cadence.value}}
    other.assert_not_called()


async def test_terminal_duplicate_returns_without_graph_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    existing = WorkflowRun(
        cadence=Cadence.DAILY,
        idempotency_key="daily:2026-07-12:2026-07-12",
        status=WorkflowStatus.SUCCEEDED,
    )
    builder = Mock()
    monkeypatch.setattr(runner, "_ensure_run", AsyncMock(return_value=existing))
    monkeypatch.setattr("analyst_engine.workflows.runner.GRAPH_BUILDERS", {Cadence.DAILY: builder})

    assert await runner.run_daily(date(2026, 7, 12)) == existing
    builder.assert_not_called()


@pytest.mark.parametrize("initial", [WorkflowStatus.PENDING, WorkflowStatus.RUNNING])
async def test_nonterminal_run_starts_or_resumes_same_checkpoint(
    monkeypatch: pytest.MonkeyPatch, initial: WorkflowStatus
) -> None:
    runner = _runner()
    run = WorkflowRun(
        cadence=Cadence.DAILY,
        idempotency_key="daily:2026-07-12:2026-07-12",
        status=initial,
    )
    running = run.model_copy(
        update={"status": WorkflowStatus.RUNNING, "checkpoint_ref": str(run.id)}
    )
    succeeded = running.model_copy(update={"status": WorkflowStatus.SUCCEEDED})
    compiled = _CompiledGraph()
    monkeypatch.setattr(runner, "_ensure_run", AsyncMock(return_value=run))
    update = AsyncMock(side_effect=[running, succeeded])
    monkeypatch.setattr(runner, "_update_run", update)
    monkeypatch.setattr(
        "analyst_engine.workflows.runner.GRAPH_BUILDERS",
        {Cadence.DAILY: Mock(return_value=_GraphBuilder(compiled))},
    )

    await runner.run_daily(date(2026, 7, 12), batch_summaries=[_summary()])

    assert compiled.calls[0][1]["configurable"]["thread_id"] == str(run.id)
    assert update.await_args_list[0].args[0].status is WorkflowStatus.RUNNING


async def test_graph_failure_is_durably_failed_and_reraised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    run = WorkflowRun(cadence=Cadence.DAILY, idempotency_key="daily:2026-07-12:2026-07-12")
    running = run.model_copy(
        update={"status": WorkflowStatus.RUNNING, "checkpoint_ref": str(run.id)}
    )
    failed = running.model_copy(update={"status": WorkflowStatus.FAILED})
    error = RetryableModelError("secret provider payload", details={"token": "secret"})
    monkeypatch.setattr(runner, "_ensure_run", AsyncMock(return_value=run))
    update = AsyncMock(side_effect=[running, failed])
    monkeypatch.setattr(runner, "_update_run", update)
    monkeypatch.setattr(
        "analyst_engine.workflows.runner.GRAPH_BUILDERS",
        {Cadence.DAILY: Mock(return_value=_GraphBuilder(_CompiledGraph(error=error)))},
    )

    with pytest.raises(RetryableModelError, match="secret provider payload"):
        await runner.run_daily(date(2026, 7, 12), batch_summaries=[_summary()])

    failure = update.await_args_list[-1].args[0]
    assert failure.status is WorkflowStatus.FAILED
    assert failure.completed_at is not None
    assert failure.error_summary == "RetryableModelError: provider operation failed"
    assert "secret" not in failure.error_summary


async def test_checkpoint_context_failure_never_marks_run_succeeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def broken_checkpointer():
        raise RuntimeError("database password")
        yield

    runner = WorkflowRunner(Mock(), Mock(), Mock(), broken_checkpointer)
    run = WorkflowRun(cadence=Cadence.DAILY, idempotency_key="daily:2026-07-12:2026-07-12")
    running = run.model_copy(
        update={"status": WorkflowStatus.RUNNING, "checkpoint_ref": str(run.id)}
    )
    failed = running.model_copy(update={"status": WorkflowStatus.FAILED})
    monkeypatch.setattr(runner, "_ensure_run", AsyncMock(return_value=run))
    update = AsyncMock(side_effect=[running, failed])
    monkeypatch.setattr(runner, "_update_run", update)

    with pytest.raises(RuntimeError, match="database password"):
        await runner.run_daily(date(2026, 7, 12), batch_summaries=[_summary()])

    assert [call.args[0].status for call in update.await_args_list] == [
        WorkflowStatus.RUNNING,
        WorkflowStatus.FAILED,
    ]
