from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import IntegrityError

from analyst_engine.domain.models import Cadence, WorkflowRun, WorkflowStatus
from analyst_engine.persistence.models import WorkflowRun as ORMWorkflowRun
from analyst_engine.persistence.repositories import (
    InvalidWorkflowRunTransitionError,
    WorkflowRunAlreadyExistsError,
    WorkflowRunIdentityError,
    WorkflowRunNotFoundError,
    create_workflow_run,
    update_workflow_run,
)


def _orm_run(run: WorkflowRun) -> ORMWorkflowRun:
    return ORMWorkflowRun(
        id=run.id,
        cadence=run.cadence.value,
        idempotency_key=run.idempotency_key,
        status=run.status.value,
        checkpoint_ref=run.checkpoint_ref,
        error_summary=run.error_summary,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


@pytest.mark.asyncio
async def test_create_workflow_run_inserts_refreshes_and_maps_persisted_row() -> None:
    run = WorkflowRun(cadence=Cadence.DAILY, idempotency_key="daily:2026-07-11")
    session = Mock()
    session.add = Mock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    created = await create_workflow_run(session, run)

    session.add.assert_called_once()
    session.flush.assert_awaited_once_with()
    session.refresh.assert_awaited_once_with(session.add.call_args.args[0])
    assert created == run


@pytest.mark.asyncio
async def test_create_workflow_run_reports_duplicate_without_overwriting() -> None:
    run = WorkflowRun(cadence=Cadence.DAILY, idempotency_key="daily:2026-07-11")
    session = Mock()
    session.add = Mock()
    session.flush = AsyncMock(
        side_effect=IntegrityError("insert", {}, Exception("unique constraint"))
    )

    with pytest.raises(
        WorkflowRunAlreadyExistsError,
        match=f"workflow run already exists: id={run.id}, idempotency_key={run.idempotency_key!r}",
    ):
        await create_workflow_run(session, run)


@pytest.mark.asyncio
async def test_update_workflow_run_updates_exact_row_and_returns_refreshed_domain() -> None:
    pending = WorkflowRun(cadence=Cadence.DAILY, idempotency_key="daily:2026-07-11")
    row = _orm_run(pending)
    result = Mock()
    result.scalar_one_or_none.return_value = row
    session = Mock()
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    running = pending.model_copy(
        update={"status": WorkflowStatus.RUNNING, "checkpoint_ref": "checkpoint-1"}
    )

    updated = await update_workflow_run(session, running)

    assert updated.id == pending.id
    assert updated.idempotency_key == pending.idempotency_key
    assert updated.status == WorkflowStatus.RUNNING
    assert updated.checkpoint_ref == "checkpoint-1"
    session.flush.assert_awaited_once_with()
    session.refresh.assert_awaited_once_with(row)


@pytest.mark.asyncio
async def test_update_workflow_run_succeeds_from_running_with_stable_identity() -> None:
    running = WorkflowRun(
        cadence=Cadence.DAILY,
        idempotency_key="daily:2026-07-11",
        status=WorkflowStatus.RUNNING,
    )
    row = _orm_run(running)
    result = Mock()
    result.scalar_one_or_none.return_value = row
    session = Mock()
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    succeeded = await update_workflow_run(
        session,
        running.model_copy(update={"status": WorkflowStatus.SUCCEEDED}),
    )

    assert succeeded.status == WorkflowStatus.SUCCEEDED
    assert succeeded.id == running.id
    assert succeeded.idempotency_key == running.idempotency_key


@pytest.mark.asyncio
async def test_update_workflow_run_never_inserts_missing_row() -> None:
    run = WorkflowRun(cadence=Cadence.DAILY, idempotency_key="daily:missing")
    result = Mock()
    result.scalar_one_or_none.return_value = None
    session = Mock()
    session.execute = AsyncMock(return_value=result)
    session.add = Mock()

    with pytest.raises(WorkflowRunNotFoundError, match=f"workflow run not found: id={run.id}"):
        await update_workflow_run(session, run)

    session.add.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (WorkflowStatus.PENDING, WorkflowStatus.SUCCEEDED),
        (WorkflowStatus.RUNNING, WorkflowStatus.PENDING),
        (WorkflowStatus.SUCCEEDED, WorkflowStatus.RUNNING),
        (WorkflowStatus.FAILED, WorkflowStatus.RUNNING),
    ],
)
async def test_update_workflow_run_rejects_invalid_transitions(
    current: WorkflowStatus, requested: WorkflowStatus
) -> None:
    persisted = WorkflowRun(
        cadence=Cadence.DAILY,
        idempotency_key="daily:2026-07-11",
        status=current,
    )
    result = Mock()
    result.scalar_one_or_none.return_value = _orm_run(persisted)
    session = Mock()
    session.execute = AsyncMock(return_value=result)

    with pytest.raises(
        InvalidWorkflowRunTransitionError,
        match=f"invalid workflow run transition: {current.value} -> {requested.value}",
    ):
        await update_workflow_run(session, persisted.model_copy(update={"status": requested}))


@pytest.mark.asyncio
async def test_update_workflow_run_allows_failure_from_pending_and_running() -> None:
    for status in (WorkflowStatus.PENDING, WorkflowStatus.RUNNING):
        persisted = WorkflowRun(
            cadence=Cadence.DAILY,
            idempotency_key=f"daily:{status.value}",
            status=status,
        )
        result = Mock()
        result.scalar_one_or_none.return_value = _orm_run(persisted)
        session = Mock()
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        session.refresh = AsyncMock()

        updated = await update_workflow_run(
            session,
            persisted.model_copy(update={"status": WorkflowStatus.FAILED, "error_summary": "boom"}),
        )

        assert updated.status == WorkflowStatus.FAILED
        assert updated.error_summary == "boom"


@pytest.mark.asyncio
async def test_update_workflow_run_is_idempotent_for_same_state() -> None:
    persisted = WorkflowRun(
        cadence=Cadence.DAILY,
        idempotency_key="daily:2026-07-11",
        status=WorkflowStatus.RUNNING,
    )
    row = _orm_run(persisted)
    result = Mock()
    result.scalar_one_or_none.return_value = row
    session = Mock()
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    updated = await update_workflow_run(session, persisted)

    assert updated == persisted


@pytest.mark.asyncio
async def test_update_workflow_run_rejects_identity_changes() -> None:
    persisted = WorkflowRun(cadence=Cadence.DAILY, idempotency_key="daily:2026-07-11")
    result = Mock()
    result.scalar_one_or_none.return_value = _orm_run(persisted)
    session = Mock()
    session.execute = AsyncMock(return_value=result)
    changed = persisted.model_copy(update={"idempotency_key": "daily:changed"})

    with pytest.raises(WorkflowRunIdentityError, match="workflow run identity is immutable"):
        await update_workflow_run(session, changed)
