"""API tests for /pipelines routes."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, Mock
from uuid import UUID

from conftest import make_client

from analyst_engine.domain.models import WorkflowStatus
from analyst_engine.pipeline.daily_brief import DailyPipelineResult

_TARGET_DATE = date(2026, 7, 13)
_WORKFLOW_RUN_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
_BRIEF_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")


def _pipeline_result(*, is_no_content: bool) -> DailyPipelineResult:
    return DailyPipelineResult(
        target_date=_TARGET_DATE,
        feeds_polled=2,
        articles_succeeded=5,
        articles_duplicate=1,
        articles_failed=0,
        batches_created=1,
        batches_reused=0,
        summaries_created=1,
        summaries_reused=0,
        summaries_selected=1,
        is_no_content=is_no_content,
        workflow_run_id=None if is_no_content else _WORKFLOW_RUN_ID,
        workflow_status=None if is_no_content else WorkflowStatus.SUCCEEDED,
        brief_id=None if is_no_content else _BRIEF_ID,
    )


def test_post_pipelines_daily_requires_auth_and_maps_result(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pipeline = Mock(run=AsyncMock(return_value=_pipeline_result(is_no_content=False)))
    client = make_client(
        monkeypatch,
        allow_unauthenticated_write=False,
        pipeline=pipeline,
    )

    unauthenticated = client.post(
        "/pipelines/daily",
        json={"target_date": "2026-07-13"},
    )
    assert unauthenticated.status_code == 401
    assert unauthenticated.json() == {"detail": "API key required"}
    pipeline.run.assert_not_awaited()

    authenticated = client.post(
        "/pipelines/daily",
        headers={"X-API-Key": "test-secret"},
        json={"target_date": "2026-07-13"},
    )

    assert authenticated.status_code == 200
    body = authenticated.json()
    assert body == {
        "target_date": "2026-07-13",
        "feeds_polled": 2,
        "articles_succeeded": 5,
        "articles_duplicate": 1,
        "articles_failed": 0,
        "batches_created": 1,
        "batches_reused": 0,
        "summaries_created": 1,
        "summaries_reused": 0,
        "summaries_selected": 1,
        "is_no_content": False,
        "workflow_run_id": str(_WORKFLOW_RUN_ID),
        "workflow_status": "succeeded",
        "brief_id": str(_BRIEF_ID),
    }
    pipeline.run.assert_awaited_once_with(_TARGET_DATE)


def test_post_pipelines_daily_maps_no_content_result(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pipeline = Mock(run=AsyncMock(return_value=_pipeline_result(is_no_content=True)))
    client = make_client(
        monkeypatch,
        allow_unauthenticated_write=True,
        pipeline=pipeline,
    )

    response = client.post(
        "/pipelines/daily",
        json={"target_date": "2026-07-13"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_no_content"] is True
    assert body["workflow_run_id"] is None
    assert body["workflow_status"] is None
    assert body["brief_id"] is None
