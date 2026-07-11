from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import MemorySaver

from analyst_engine.domain.models import (
    BatchSummary,
    Cadence,
    Citation,
    WorkflowRun,
    WorkflowStatus,
)
from analyst_engine.models.gateway import ModelUsage, RetryableModelError, TerminalModelError
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
    monkeypatch.setattr(runner, "_claim_run", AsyncMock(return_value=running))
    monkeypatch.setattr(runner, "_load_context", AsyncMock(return_value=(None, [])))
    monkeypatch.setattr(runner, "_update_run", AsyncMock(return_value=succeeded))
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


async def test_pending_run_starts_or_resumes_same_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    run = WorkflowRun(
        cadence=Cadence.DAILY,
        idempotency_key="daily:2026-07-12:2026-07-12",
        status=WorkflowStatus.PENDING,
    )
    running = run.model_copy(
        update={"status": WorkflowStatus.RUNNING, "checkpoint_ref": str(run.id)}
    )
    succeeded = running.model_copy(update={"status": WorkflowStatus.SUCCEEDED})
    compiled = _CompiledGraph()
    monkeypatch.setattr(runner, "_ensure_run", AsyncMock(return_value=run))
    monkeypatch.setattr(runner, "_claim_run", AsyncMock(return_value=running))
    monkeypatch.setattr(runner, "_load_context", AsyncMock(return_value=(None, [])))
    update = AsyncMock(return_value=succeeded)
    monkeypatch.setattr(runner, "_update_run", update)
    monkeypatch.setattr(
        "analyst_engine.workflows.runner.GRAPH_BUILDERS",
        {Cadence.DAILY: Mock(return_value=_GraphBuilder(compiled))},
    )

    await runner.run_daily(date(2026, 7, 12), batch_summaries=[_summary()])

    assert compiled.calls[0][1]["configurable"]["thread_id"] == str(run.id)
    assert update.await_args_list[0].args[0].status is WorkflowStatus.SUCCEEDED


async def test_running_duplicate_returns_without_invoking_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    running = WorkflowRun(
        cadence=Cadence.DAILY,
        idempotency_key="daily:2026-07-12:2026-07-12",
        status=WorkflowStatus.RUNNING,
    )
    builder = Mock()
    monkeypatch.setattr(runner, "_ensure_run", AsyncMock(return_value=running))
    monkeypatch.setattr("analyst_engine.workflows.runner.GRAPH_BUILDERS", {Cadence.DAILY: builder})

    assert await runner.run_daily(date(2026, 7, 12)) == running
    builder.assert_not_called()


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
    monkeypatch.setattr(runner, "_claim_run", AsyncMock(return_value=running))
    monkeypatch.setattr(runner, "_load_context", AsyncMock(return_value=(None, [])))
    update = AsyncMock(return_value=failed)
    monkeypatch.setattr(runner, "_update_run", update)
    monkeypatch.setattr(
        "analyst_engine.workflows.runner.GRAPH_BUILDERS",
        {Cadence.DAILY: Mock(return_value=_GraphBuilder(_CompiledGraph(error=error)))},
    )

    with pytest.raises(RetryableModelError, match="secret provider payload"):
        await runner.run_daily(date(2026, 7, 12), batch_summaries=[_summary()])

    failure = update.await_args_list[0].args[0]
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
    monkeypatch.setattr(runner, "_claim_run", AsyncMock(return_value=running))
    monkeypatch.setattr(runner, "_load_context", AsyncMock(return_value=(None, [])))
    update = AsyncMock(return_value=failed)
    monkeypatch.setattr(runner, "_update_run", update)

    with pytest.raises(RuntimeError, match="database password"):
        await runner.run_daily(date(2026, 7, 12), batch_summaries=[_summary()])

    assert [call.args[0].status for call in update.await_args_list] == [WorkflowStatus.FAILED]


@pytest.mark.parametrize(
    "error",
    [TerminalModelError("secret terminal payload"), ValueError("malformed secret payload")],
)
async def test_terminal_or_malformed_provider_output_is_failed_and_reraised(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    runner = _runner()
    run = WorkflowRun(cadence=Cadence.DAILY, idempotency_key="daily:2026-07-12:2026-07-12")
    running = run.model_copy(update={"status": WorkflowStatus.RUNNING})
    failed = running.model_copy(update={"status": WorkflowStatus.FAILED})
    monkeypatch.setattr(runner, "_ensure_run", AsyncMock(return_value=run))
    monkeypatch.setattr(runner, "_claim_run", AsyncMock(return_value=running))
    monkeypatch.setattr(runner, "_load_context", AsyncMock(return_value=(None, [])))
    update = AsyncMock(return_value=failed)
    monkeypatch.setattr(runner, "_update_run", update)
    monkeypatch.setattr(
        "analyst_engine.workflows.runner.GRAPH_BUILDERS",
        {Cadence.DAILY: Mock(return_value=_GraphBuilder(_CompiledGraph(error=error)))},
    )

    with pytest.raises(type(error)):
        await runner.run_daily(date(2026, 7, 12), batch_summaries=[_summary()])

    statuses = [call.args[0].status for call in update.await_args_list]
    assert statuses == [WorkflowStatus.FAILED]
    summary = update.await_args_list[-1].args[0].error_summary
    assert summary is not None
    assert "secret" not in summary


async def test_success_lifecycle_update_failure_attempts_failed_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    run = WorkflowRun(cadence=Cadence.DAILY, idempotency_key="daily:2026-07-12:2026-07-12")
    running = run.model_copy(update={"status": WorkflowStatus.RUNNING})
    failed = running.model_copy(update={"status": WorkflowStatus.FAILED})
    compiled = _CompiledGraph()
    monkeypatch.setattr(runner, "_ensure_run", AsyncMock(return_value=run))
    monkeypatch.setattr(runner, "_claim_run", AsyncMock(return_value=running))
    monkeypatch.setattr(runner, "_load_context", AsyncMock(return_value=(None, [])))
    update = AsyncMock(side_effect=[RuntimeError("database password"), failed])
    monkeypatch.setattr(runner, "_update_run", update)
    monkeypatch.setattr(
        "analyst_engine.workflows.runner.GRAPH_BUILDERS",
        {Cadence.DAILY: Mock(return_value=_GraphBuilder(compiled))},
    )

    with pytest.raises(RuntimeError, match="database password"):
        await runner.run_daily(date(2026, 7, 12), batch_summaries=[_summary()])

    assert len(compiled.calls) == 1
    assert [call.args[0].status for call in update.await_args_list] == [
        WorkflowStatus.SUCCEEDED,
        WorkflowStatus.FAILED,
    ]
    assert update.await_args_list[-1].args[0].error_summary == (
        "RuntimeError: workflow execution failed"
    )


async def test_analytical_commit_failure_rolls_back_and_marks_run_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = Mock()
    session.commit = AsyncMock(side_effect=RuntimeError("database password"))
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session_factory = Mock(return_value=session)
    gateway = Mock()

    async def generate(**kwargs: Any) -> tuple[Any, ModelUsage]:
        schema = kwargs["output_schema"]
        return (
            schema(
                brief_content="brief",
                narrative_state={"theme": "test"},
                change_log=["changed"],
            ),
            ModelUsage(model="fake"),
        )

    gateway.generate = generate

    @asynccontextmanager
    async def checkpointer_factory():
        yield MemorySaver()

    runner = WorkflowRunner(Mock(), gateway, session_factory, checkpointer_factory)
    run = WorkflowRun(cadence=Cadence.DAILY, idempotency_key="daily:2026-07-12:2026-07-12")
    running = run.model_copy(update={"status": WorkflowStatus.RUNNING})
    failed = running.model_copy(update={"status": WorkflowStatus.FAILED})
    monkeypatch.setattr(runner, "_ensure_run", AsyncMock(return_value=run))
    monkeypatch.setattr(runner, "_claim_run", AsyncMock(return_value=running))
    monkeypatch.setattr(runner, "_load_context", AsyncMock(return_value=(None, [])))
    update = AsyncMock(return_value=failed)
    monkeypatch.setattr(runner, "_update_run", update)
    save_narrative = AsyncMock()
    save_expectation = AsyncMock()
    save_brief = AsyncMock()
    monkeypatch.setattr("analyst_engine.workflows.graphs.save_narrative_version", save_narrative)
    monkeypatch.setattr("analyst_engine.workflows.graphs.save_brief", save_brief)
    monkeypatch.setattr(
        "analyst_engine.workflows.graphs.save_prediction_expectation", save_expectation
    )

    with pytest.raises(RuntimeError, match="database password"):
        await runner.run_daily(date(2026, 7, 12), batch_summaries=[_summary()])

    save_narrative.assert_awaited_once()
    save_brief.assert_awaited_once()
    session.commit.assert_awaited_once()
    session.rollback.assert_awaited_once()
    assert [call.args[0].status for call in update.await_args_list] == [
        WorkflowStatus.FAILED,
    ]
